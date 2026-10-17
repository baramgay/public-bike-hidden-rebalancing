"""ASOS 시간자료(15057210) 창원155 2023-01-01~2025-12-31 수집. 키는 .env.local에서만 읽고 출력/저장하지 않는다."""
import json, sys, time, hashlib, datetime as dt, urllib.parse, urllib.request, csv
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'data/raw/weather/kma_asos_2023_2025'
EP = 'https://apis.data.go.kr/1360000/AsosHourlyInfoService/getWthrDataList'
def key():
    for l in (ROOT/'.env.local').read_text(encoding='utf-8').splitlines():
        if l.startswith('DATA_GO_KR_SERVICE_KEY='):
            return urllib.parse.unquote(l.split('=',1)[1].strip().strip('"\''))
    sys.exit(2)
K = key()
def call(p):
    q = urllib.parse.urlencode({'serviceKey':K, **p})
    try:
        b = urllib.request.urlopen(EP+'?'+q, timeout=60).read()
    except Exception as e:
        return None, f'HTTP_ERROR {type(e).__name__}'
    if K.encode() in b: return None, 'KEY_REFLECTED'
    try: j = json.loads(b)
    except Exception:
        t = b.decode('utf-8','replace'); import re
        m = re.search(r'<returnAuthMsg>(.*?)</', t) or re.search(r'<resultMsg>(.*?)</', t)
        return None, 'NON_JSON ' + (m.group(1) if m else t[:80])
    return j, None
def main():
    run = dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'); rd = OUT/run; rd.mkdir(parents=True)
    meta = {'source':'기상청_지상(종관, ASOS) 시간자료 조회서비스 15057210','endpoint':EP,'stnIds':'155','run_utc':run,'calls':0,'chunks':[]}
    rows = []
    d = dt.date(2023,1,1); end = dt.date(2025,12,31)
    while d <= end:
        e = dt.date(d.year + d.month//12, d.month%12+1, 1) - dt.timedelta(days=1)
        e = min(e, end); page = 1; got = []
        while True:
            p = {'pageNo':page,'numOfRows':999,'dataType':'JSON','dataCd':'ASOS','dateCd':'HR','startDt':d.strftime('%Y%m%d'),'startHh':'00','endDt':e.strftime('%Y%m%d'),'endHh':'23','stnIds':'155'}
            j, err = call(p); meta['calls'] += 1; time.sleep(0.3)
            if err: meta['chunks'].append({'start':str(d),'end':str(e),'page':page,'error':err}); break
            h = j['response']['header']
            if str(h.get('resultCode')) not in ('00','0'):
                meta['chunks'].append({'start':str(d),'end':str(e),'page':page,'error':f"{h.get('resultCode')} {h.get('resultMsg')}"}); err='x'; break
            fn = rd/f'asos155_hr_{d:%Y%m}_p{page}.json'; fn.write_bytes(json.dumps(j, ensure_ascii=False).encode('utf-8'))
            body = j['response']['body']; it = body.get('items') or {}; it = it.get('item', []) if isinstance(it, dict) else []
            if isinstance(it, dict): it = [it]
            got += it; tc = int(body.get('totalCount', 0))
            if len(got) >= tc or not it: break
            page += 1
        if err:
            meta['status'] = 'FAILED'; break
        meta['chunks'].append({'start':str(d),'end':str(e),'rows':len(got),'totalCount':tc}); rows += got
        d = e + dt.timedelta(days=1)
    # QC
    if rows:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with open(rd/'asos155_hourly_2023_2025.csv','w',newline='',encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
        tms = [r.get('tm') for r in rows]; s = set(tms)
        exp = set(); t = dt.datetime(2023,1,1,0)
        while t <= dt.datetime(2025,12,31,23): exp.add(t.strftime('%Y-%m-%d %H:%M')); t += dt.timedelta(hours=1)
        miss = sorted(exp - s)
        meta['qc'] = {'rows':len(rows),'expected_hours':len(exp),'unique_tm':len(s),'duplicates':len(tms)-len(s),'missing_hours':len(miss),'missing_sample':miss[:50],'extra':len(s-exp),'stations':sorted({str(r.get('stnId')) for r in rows}),
            'empty_by_field':{c: sum(1 for r in rows if r.get(c) in (None,'')) for c in cols}}
        meta['csv_sha256'] = hashlib.sha256((rd/'asos155_hourly_2023_2025.csv').read_bytes()).hexdigest()
        meta.setdefault('status', 'COMPLETE' if not miss and len(tms)==len(s) else 'INCOMPLETE')
    (rd/'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k:v for k,v in meta.items() if k!='chunks'} | {'last_chunk':meta['chunks'][-1:]}, ensure_ascii=False)[:3000])
main()
