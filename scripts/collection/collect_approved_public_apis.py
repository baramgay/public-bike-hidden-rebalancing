"""Collect only approved ASOS daily and current TAGO data. Never logs credential URLs."""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 'https://apis.data.go.kr/'
ENDPOINTS = {
    'asos_daily': '1360000/AsosDalyInfoService/getWthrDataList',
    'cities': '1613000/BusRouteInfoInqireService/getCtyCodeList',
    'stops': '1613000/BusSttnInfoInqireService/getSttnNoList',
    'routes': '1613000/BusRouteInfoInqireService/getRouteNoList',
    'route_stops': '1613000/BusRouteInfoInqireService/getRouteAcctoThrghSttnList',
    'arrivals': '1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList',
}
DOCS = {
    'asos_daily': 'https://www.data.go.kr/data/15059093/openapi.do',
    'cities': 'https://www.data.go.kr/data/15098529/openapi.do',
    'routes': 'https://www.data.go.kr/data/15098529/openapi.do',
    'route_stops': 'https://www.data.go.kr/data/15098529/openapi.do',
    'stops': 'https://www.data.go.kr/data/15098534/openapi.do',
    'arrivals': 'https://www.data.go.kr/data/15098530/openapi.do',
}

class CollectionError(Exception):
    pass

def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def normalize_key(value):
    # unquote preserves literal '+'; unquote_plus would corrupt a decoded key.
    return urllib.parse.unquote(value.strip())

def load_key(path):
    if not path.exists():
        return ''
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        match = re.match(r'^\s*(?:export\s+)?DATA_GO_KR_SERVICE_KEY\s*=\s*(.*?)\s*$',line)
        if match:
            value = match.group(1)
            if len(value)>=2 and value[0]==value[-1] and value[0] in '\"\'':
                value=value[1:-1]
            return normalize_key(value)
    return ''

def parse_payload(payload):
    try:
        response=payload['response']
        header=response['header']
        code=str(header['resultCode']).strip()
    except (KeyError,TypeError):
        raise CollectionError('invalid_response_envelope') from None
    if code not in ('00','0'):
        # Do not echo resultMsg: a gateway may reflect a submitted credential.
        safe_code=code if re.fullmatch(r'[A-Za-z0-9_\-]{1,60}',code) else 'unknown'
        raise CollectionError('agency_result_code_'+safe_code)
    body=response.get('body') or {}
    container=body.get('items') or {}
    items=container.get('item',[]) if isinstance(container,dict) else []
    if isinstance(items,dict):items=[items]
    if items in ('',None):items=[]
    if not isinstance(items,list) or any(not isinstance(x,dict) for x in items):
        raise CollectionError('invalid_item_schema')
    return items,body

def validate_page(body,page,size,count,expected_total):
    if 'pageNo' in body and int(body['pageNo'])!=page:
        raise CollectionError('response_page_number_mismatch')
    total=int(body['totalCount']) if 'totalCount' in body else None
    if expected_total is not None and total!=expected_total:
        raise CollectionError('totalCount_changed_during_collection')
    if total is not None:
        wanted=min(size,max(0,total-(page-1)*size))
        if count!=wanted:raise CollectionError('page_item_count_mismatch')
    return total

def daily_coverage(rows,year):
    start=dt.date(year,1,1);end=dt.date(year+1,1,1)
    expected={(start+dt.timedelta(days=i)).isoformat() for i in range((end-start).days)}
    dates=[str(r.get('tm','')) for r in rows]
    counts=collections.Counter(dates)
    return {'expected_days':len(expected),'actual_rows':len(rows),
            'actual_date_min':min(dates) if dates else None,'actual_date_max':max(dates) if dates else None,
            'duplicate_dates':sum(v-1 for v in counts.values()),
            'missing_dates':sorted(expected-set(dates)),
            'unexpected_dates':sorted(set(dates)-expected),
            'wrong_station_rows':sum(str(r.get('stnId',''))!='155' for r in rows)}

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def write_csv(path,rows):
    if not rows:return
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)

class Collector:
    def __init__(self,key,run_dir,meta_dir):
        self.key=key;self.run_dir=run_dir;self.meta_dir=meta_dir
        self.calls=collections.Counter();self.files=[];self.datasets=[];self.derived_files=[]
        self.last_call=0.;self.current_operation=None

    def get(self,operation,params,label):
        self.current_operation=operation
        # Conservative run cap well below approved 10,000/day/operation.
        if self.calls[operation]>=1000:raise CollectionError('run_operation_budget_1000_reached')
        time.sleep(max(0.,0.3-(time.monotonic()-self.last_call)))
        key_name='serviceKey'
        request_params={**params,key_name:self.key}
        url=BASE+ENDPOINTS[operation]+'?'+urllib.parse.urlencode(request_params)
        request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'NubijaResearchDataCollector/1.0'})
        self.calls[operation]+=1;self.last_call=time.monotonic();stamp=utcnow()
        try:
            with urllib.request.urlopen(request,timeout=60) as response:
                raw=response.read();status=response.status
        except urllib.error.HTTPError as exc:
            raise CollectionError('http_status_'+str(exc.code)) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise CollectionError('network_or_timeout_error') from None
        if status!=200:raise CollectionError('http_status_'+str(status))
        # Preserve response bytes only if they do not contain a reflected credential.
        variants={self.key,urllib.parse.quote(self.key,safe=''),urllib.parse.quote_plus(self.key)}
        if any(v.encode() in raw for v in variants if v):
            raise CollectionError('credential_reflected_response_not_saved')
        try:payload=json.loads(raw.decode('utf-8-sig'));suffix='.json'
        except (UnicodeError,json.JSONDecodeError):payload=None;suffix='.non_json.txt'
        dest=self.run_dir/operation/(label+suffix)
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        self.files.append({'path':str(dest.relative_to(ROOT)),'bytes':len(raw),
                           'sha256':hashlib.sha256(raw).hexdigest(),'collected_utc':stamp,
                           'endpoint':BASE+ENDPOINTS[operation],'document':DOCS[operation],
                           'parameters_without_key':params})
        self.checkpoint('running')
        if payload is None:raise CollectionError('non_json_response_saved_check_gateway_or_permissions')
        return parse_payload(payload)

    def all_pages(self,operation,params,label,paginated=True):
        size=100;page=1;expected_total=None;rows=[];fingerprints=set()
        while True:
            args={**params}
            args.update({'dataType':'JSON'} if operation=='asos_daily' else {'_type':'json'})
            if paginated:args.update(pageNo=page,numOfRows=size)
            items,body=self.get(operation,args,f'{label}_page_{page:04d}')
            total=validate_page(body,page,size,len(items),expected_total)
            if page==1:expected_total=total
            if paginated and total is None:raise CollectionError('missing_totalCount_for_paginated_operation')
            fingerprint=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if items and fingerprint in fingerprints:raise CollectionError('repeated_page_content')
            fingerprints.add(fingerprint);rows.extend(items)
            if not paginated or len(rows)==total:break
            if not items:raise CollectionError('empty_page_before_totalCount')
            page+=1
        if expected_total is not None and len(rows)!=expected_total:
            raise CollectionError('final_count_does_not_match_totalCount')
        fields=list(dict.fromkeys(k for r in rows for k in r))
        self.datasets.append({'operation':operation,'label':label,'rows':len(rows),'totalCount':expected_total,
            'pages':page,'columns':fields,'blank_or_missing':{k:sum(r.get(k) in ('',None) for r in rows) for k in fields}})
        self.save_csv(self.run_dir/'derived_csv'/f'{label}.csv',rows)
        self.checkpoint('running')
        return rows

    def save_csv(self,path,rows):
        write_csv(path,rows)
        if path.exists():
            raw=path.read_bytes()
            self.derived_files.append({'path':str(path.relative_to(ROOT)),'bytes':len(raw),
                'sha256':hashlib.sha256(raw).hexdigest(),'rows':len(rows),'format':'derived CSV; original field values retained'})

    def checkpoint(self,status,error=None):
        value={'status':status,'updated_utc':utcnow(),'error':error,
               'failed_operation':self.current_operation if error else None,
               'calls_by_operation':dict(self.calls),'files':self.files,'derived_files':self.derived_files,'datasets':self.datasets,'endpoint_documents':DOCS,'endpoints_without_key':{k:BASE+v for k,v in ENDPOINTS.items()},
               'definitions':{'asos_daily':'Historical daily ASOS station 155. Not hourly. °C/mm/m/s; blank precipitation is not automatically zero.',
                'tago':'Current city/stop/route data at collection time; not historical 2023–2025 schedules.',
                'arrivals':'Optional one-stop current predicted arrival sample; not observed trip or historical arrival data.'},
               'licenses':{'ASOS':'KOGL type 1 attribution','TAGO':'data.go.kr unrestricted'},
               'hourly_asos_15057210':'not approved; never called',
               'quota':'approved 10000/day/operation; this run limits each operation to1000; no automatic retries'}
        write_json(self.meta_dir/'run.json',value)
        lines=['# 승인된 공공 API 수집 실행 기록','',f'상태: {status}',f'갱신 UTC: {value["updated_utc"]}',
               '','인증키와 인증 URL을 기록하지 않았다. 원형 응답과 파생 CSV는 별도 보존한다.',
               '','ASOS는 일자료, TAGO는 수집시점의 현재 자료다. 시간자료와 과거 버스 운행 실적으로 해석하지 않는다.',
               '',f'실패: {error or "없음"}',f'작업별 호출수: {dict(self.calls)}',
               '','상세 필드별 결측·페이지 수·기간·파일 해시는 같은 폴더 run.json을 확인한다.']
        (self.meta_dir/'run.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only',choices=['all','asos','tago'],default='all')
    parser.add_argument('--arrival-node-id',help='Optional single node ID from collected stops; one current sample only')
    args=parser.parse_args(argv)
    key=load_key(ROOT/'.env.local')
    if not key:
        print('DATA_GO_KR_SERVICE_KEY is absent in .env.local; no network request made.')
        return 2
    run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    collector=Collector(key,ROOT/'data/raw/approved_public_apis'/run_id,ROOT/'data/metadata/approved_public_apis'/run_id)
    collector.meta_dir.mkdir(parents=True,exist_ok=False)
    try:
        if args.only in ('all','asos'):
            for year in (2023,2024,2025):
                rows=collector.all_pages('asos_daily',{'dataCd':'ASOS','dateCd':'DAY','stnIds':'155',
                    'startDt':f'{year}0101','endDt':f'{year}1231'},f'asos155_daily_{year}')
                report=daily_coverage(rows,year);collector.datasets[-1]['coverage']=report
                if report['missing_dates'] or report['unexpected_dates'] or report['duplicate_dates'] or report['wrong_station_rows']:
                    raise CollectionError(f'asos_{year}_calendar_or_station_coverage_incomplete')
        if args.only in ('all','tago'):
            cities=collector.all_pages('cities',{},'tago_city_codes',paginated=False)
            candidates=[r for r in cities if str(r.get('cityname','')).strip() in ('창원','창원시')]
            if len(candidates)!=1:raise CollectionError('changwon_city_not_uniquely_identified')
            city=str(candidates[0]['citycode'])
            stops=collector.all_pages('stops',{'cityCode':city},'changwon_stops')
            routes=collector.all_pages('routes',{'cityCode':city},'changwon_routes')
            ids=[str(r.get('routeid','')).strip() for r in routes]
            if not ids or any(not x for x in ids) or len(set(ids))!=len(ids):
                raise CollectionError('route_ids_empty_or_duplicated')
            combined=[]
            for index,route_id in enumerate(ids,1):
                rows=collector.all_pages('route_stops',{'cityCode':city,'routeId':route_id},f'route_{index:04d}_stops')
                combined.extend({'requested_routeid':route_id,**r} for r in rows)
            collector.save_csv(collector.run_dir/'derived_csv/changwon_all_route_stops.csv',combined)
            if args.arrival_node_id:
                if args.arrival_node_id not in {str(r.get('nodeid')) for r in stops}:
                    raise CollectionError('arrival_node_not_in_collected_changwon_stops')
                collector.all_pages('arrivals',{'cityCode':city,'nodeId':args.arrival_node_id},'single_stop_arrival_sample')
        elif args.arrival_node_id:
            raise CollectionError('arrival_sample_requires_tago_mode')
        collector.checkpoint('complete')
        print('Collection complete. Metadata: '+str(collector.meta_dir.relative_to(ROOT)))
        return 0
    except CollectionError as exc:
        collector.checkpoint('failed',str(exc))
        print('Collection stopped: '+str(exc)+'. Metadata: '+str(collector.meta_dir.relative_to(ROOT)))
        return 1
    except Exception as exc:
        # No traceback or exception string: urllib exceptions can include authenticated URLs.
        collector.checkpoint('failed','unexpected_'+type(exc).__name__)
        print('Collection stopped; see sanitized run metadata.')
        return 1

if __name__=='__main__':
    sys.exit(main())


