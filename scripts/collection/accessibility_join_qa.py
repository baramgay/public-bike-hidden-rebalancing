"""원본 보존본: scripts/archive/collection_20261016/. 실행 시에만 로컬 검증한다."""

def main():
    """Read-only source audit and spherical straight-line accessibility screening.
    No routing API, geocoding, model, optimization, package installation, or raw edits.
    """
    from pathlib import Path
    from datetime import datetime, timezone
    import hashlib, json, math, platform
    import numpy as np
    import pandas as pd
    ROOT=Path(__file__).resolve().parents[2]
    OUT=ROOT/'data/processed/accessibility_qa';OUT.mkdir(parents=True,exist_ok=True)
    META=ROOT/'data/metadata/accessibility_join_qa.md'
    SP=ROOT/'data/raw/nubija_stations/nubija_stations_2023_2025.xlsx'
    BP=ROOT/'data/raw/transit/bus_stops_15037805_0.csv'
    R=6371008.8
    
    def hav(lat1,lon1,lat2,lon2):
        lat1,lon1,lat2,lon2=map(np.radians,(lat1,lon1,lat2,lon2))
        a=np.sin((lat2-lat1)/2)**2+np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
        a=np.clip(a,0,1)
        return R*2*np.arctan2(np.sqrt(a),np.sqrt(1-a))
    
    def save(df,name):
        p=OUT/name;df.to_csv(p,index=False,encoding='utf-8-sig',float_format='%.6f');return str(p)
    
    def audit_coords(d,label):
        lat=pd.to_numeric(d['위도'],errors='coerce');lon=pd.to_numeric(d['경도'],errors='coerce')
        global_ok=lat.between(-90,90)&lon.between(-180,180)
        regional_ok=lat.between(34.9,35.5)&lon.between(128.3,129.1)
        return {'source':label,'rows':len(d),'missing_or_nonnumeric_lat':int(lat.isna().sum()),'missing_or_nonnumeric_lon':int(lon.isna().sum()),'outside_global_range':int((~global_ok).sum()),'outside_screening_box':int((~regional_ok).sum()),'swapped_order_invalid_latitude':int((~lon.between(-90,90)).sum()),'lat_min':float(lat.min()),'lat_max':float(lat.max()),'lon_min':float(lon.min()),'lon_max':float(lon.max())}
    
    annual=[];qa=[];summ=[]
    for year in [2023,2024,2025]:
        d=pd.read_excel(SP,sheet_name=f'{year}년',dtype=str).fillna('');d.insert(0,'reference_year',year)
        if not (d['터미널번호'].duplicated().sum() == 0): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 34")
        if not (set(d['사용유무']) == {'사용함', '사용안함'}): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 35")
        qa.append(audit_coords(d,f'station_{year}'));annual.append(d)
        summ.append({'reference_year':year,'rows':len(d),'unique_station_codes':d['터미널번호'].nunique(),'active':int(d['사용유무'].eq('사용함').sum()),'inactive':int(d['사용유무'].eq('사용안함').sum())})
    annual=pd.concat(annual,ignore_index=True)
    s=annual[(annual['reference_year']==2025)&annual['사용유무'].eq('사용함')].copy().reset_index(drop=True)
    if not (len(s) == 454 and s['터미널번호'].is_unique): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 40")
    b=pd.read_csv(BP,encoding='utf-8-sig',dtype=str,keep_default_na=False)
    if not (len(b) == 3526 and b['정류소아이디'].is_unique): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 42")
    qa.append(audit_coords(b,'bus_20251231'))
    if not (all((q['outside_global_range'] == 0 and q['missing_or_nonnumeric_lat'] == 0 and (q['missing_or_nonnumeric_lon'] == 0) for q in qa))): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 44")
    lat=s['위도'].astype(float).to_numpy();lon=s['경도'].astype(float).to_numpy()
    blat=b['위도'].astype(float).to_numpy();blon=b['경도'].astype(float).to_numpy()
    D=hav(lat[:,None],lon[:,None],blat[None,:],blon[None,:])
    nearest=D.argmin(axis=1);dist=D.min(axis=1)
    # Independent scalar check of first/middle/last points and unit/order boundaries.
    for i in [0,len(s)//2,len(s)-1]:
        j=int(nearest[i]);a1,l1,a2,l2=map(math.radians,[lat[i],lon[i],blat[j],blon[j]])
        aa=math.sin((a2-a1)/2)**2+math.cos(a1)*math.cos(a2)*math.sin((l2-l1)/2)**2
        scalar=R*2*math.atan2(math.sqrt(aa),math.sqrt(1-aa))
        if not (abs(scalar - dist[i]) < 1e-06): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 54")
    if not (hav(np.array([0.0]), np.array([0.0]), np.array([0.0]), np.array([0.0]))[0] == 0): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 55")
    if not (111000 < float(hav(np.array([0.0]), np.array([0.0]), np.array([0.0]), np.array([1.0]))[0]) < 112000): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 56")
    res=s.copy();res['nearest_stop_straight_m']=dist
    for c in ['정류소아이디','서비스아이디','정류소명','방면','유형','관할관청','위도','경도']:
        res['nearest_stop_'+c]=b.iloc[nearest][c].to_numpy()
    res['nearest_stop_literal_virtual_name']=res['nearest_stop_정류소명'].str.contains('가상',regex=False)
    not_virtual=~b['정류소명'].str.contains('가상',regex=False).to_numpy()
    res['nearest_excluding_literal_virtual_name_m']=D[:,not_virtual].min(axis=1)
    nonvirtual_nearest=np.flatnonzero(not_virtual)[D[:,not_virtual].argmin(axis=1)]
    for c in ['정류소아이디','정류소명','방면','위도','경도']:
        res['nearest_nonvirtual_name_'+c]=b.iloc[nonvirtual_nearest][c].to_numpy()
    local=b['관할관청'].eq('379').to_numpy()
    res['nearest_authority_379_only_m']=D[:,local].min(axis=1)
    for threshold in [100,300,500,1000]:
        counts=(D<=threshold).sum(axis=1);res[f'stop_id_count_within_{threshold}m']=counts
        res[f'distinct_stop_name_count_within_{threshold}m']=[b.loc[D[i]<=threshold,'정류소명'].nunique() for i in range(len(s))]
        res[f'distinct_coordinate_count_within_{threshold}m']=[b.loc[D[i]<=threshold,['위도','경도']].drop_duplicates().shape[0] for i in range(len(s))]
        res[f'stop_id_count_no_literal_virtual_within_{threshold}m']=(D[:,not_virtual]<=threshold).sum(axis=1)
        if not ((res[f'distinct_stop_name_count_within_{threshold}m'] <= counts).all()): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 73")
    for lo,hi in [(100,300),(300,500),(500,1000)]:
        if not ((res[f'stop_id_count_within_{lo}m'] <= res[f'stop_id_count_within_{hi}m']).all()): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 75")
    # A radius count is a directional stop-ID count; names/coordinates are sensitivity counts, not official merged places.
    pairs=[]
    for name,g in b.groupby('정류소명',sort=False):
        ix=g.index.to_numpy()
        for pos,i in enumerate(ix):
            for j in ix[pos+1:]:
                dd=float(hav(blat[i],blon[i],blat[j],blon[j]))
                if dd<=100:
                    pairs.append({'stop_name':name,'id_a':b.at[i,'정류소아이디'],'id_b':b.at[j,'정류소아이디'],'direction_a':b.at[i,'방면'],'direction_b':b.at[j,'방면'],'distance_m':dd,'different_nonblank_direction':bool(b.at[i,'방면'] and b.at[j,'방면'] and b.at[i,'방면']!=b.at[j,'방면'])})
    pairs=pd.DataFrame(pairs)
    co_dup=b[b.duplicated(['위도','경도'],keep=False)].copy()
    service_dup=b[b['서비스아이디'].ne('')&b['서비스아이디'].duplicated(keep=False)].copy()
    # Coordinates of repeated IDs across years are compared, never pooled into the 2025 denominator.
    comparison=[]
    for code,g in annual.groupby('터미널번호',sort=False):
        row={'station_code':code,'years_present':','.join(g['reference_year'].astype(str)),'year_count':len(g)}
        for y in [2023,2024,2025]:
            q=g[g['reference_year'].eq(y)];row[f'status_{y}']=q['사용유무'].iloc[0] if len(q) else ''
        if len(g)>1:
            first=g.iloc[0];last=g.iloc[-1];row['first_last_coordinate_shift_m']=float(hav(float(first['위도']),float(first['경도']),float(last['위도']),float(last['경도'])))
        else:row['first_last_coordinate_shift_m']=np.nan
        comparison.append(row)
    comparison=pd.DataFrame(comparison)
    summary=[]
    for gu,g in res.groupby('구'):
        row={'district':gu,'active_stations':len(g),'nearest_straight_median_m':g['nearest_stop_straight_m'].median(),'nearest_straight_mean_m':g['nearest_stop_straight_m'].mean(),'nearest_straight_max_m':g['nearest_stop_straight_m'].max()}
        for t in [100,300,500,1000]:
            row[f'stations_with_stop_within_{t}m']=int(g[f'stop_id_count_within_{t}m'].gt(0).sum())
            row[f'mean_stop_ids_within_{t}m']=g[f'stop_id_count_within_{t}m'].mean()
            row[f'mean_distinct_names_within_{t}m']=g[f'distinct_stop_name_count_within_{t}m'].mean()
        summary.append(row)
    summary=pd.DataFrame(summary)
    if not (summary['active_stations'].sum() == 454): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 108")
    # 20 proposed route-audit cases; physical barriers are hypotheses, not observed facts.
    selected={}
    def choose(i,reason):
        code=res.at[i,'터미널번호']
        if code in selected:selected[code]['sample_reason']+='; '+reason
        else:
            row=res.loc[i].to_dict();row['sample_reason']=reason;selected[code]=row
    for gu,g in res.groupby('구'):
        choose(g['nearest_stop_straight_m'].idxmax(),'구별 최근접 직선거리 최대: 실제 보행 우회 및 입구 위치 확인')
        choose(g['nearest_stop_straight_m'].idxmin(),'구별 최근접 직선거리 최소: 근거리 대조 표본, 횡단 가능 여부 확인')
    for i in res.sort_values('nearest_stop_straight_m',ascending=False).index[:5]:choose(i,'전체 원거리 상위5: 도보 연결 및 좌표 적합성 확인')
    barrier=res[res['nearest_stop_straight_m'].le(150)&res['터미널명'].str.contains('대교|교사거리|교앞|사거리|하천|항|수변|육교|터널|다리',regex=True)]
    for i in barrier.sort_values('nearest_stop_straight_m').index:
        if len(selected)>=20:break
        choose(i,'명칭 기반 사거리/하천/항 등 장벽 확인 후보: 장벽 실재·우회 여부 미확인')
    for i in res.sort_values('nearest_stop_straight_m',ascending=False).index:
        if len(selected)>=20:break
        choose(i,'원거리 보완 표본')
    samples=pd.DataFrame(selected.values()).reset_index(drop=True)
    if not (10 <= len(samples) <= 20): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 128")
    outputs=[]
    for df,name in [(res,'station_2025_active_stop_accessibility.csv'),(summary,'district_summary.csv'),(pd.DataFrame(summ),'station_year_status_summary.csv'),(comparison,'station_cross_year_code_audit.csv'),(pd.DataFrame(qa),'coordinate_qa.csv'),(pairs,'same_name_stop_pairs_within_100m.csv'),(co_dup,'bus_exact_coordinate_duplicates.csv'),(service_dup,'bus_nonblank_service_id_duplicates.csv'),(samples,'proposed_walking_route_samples.csv')]:outputs.append(save(df,name))
    metrics={'active_stations':len(res),'nearest_distance_m':res['nearest_stop_straight_m'].describe(percentiles=[.25,.5,.75,.9,.95]).to_dict(),'stations_no_stop_within_m':{t:int(res[f'stop_id_count_within_{t}m'].eq(0).sum()) for t in [100,300,500,1000]},'stations_no_nonvirtual_name_stop_within_m':{t:int(res[f'stop_id_count_no_literal_virtual_within_{t}m'].eq(0).sum()) for t in [100,300,500,1000]},'bus_rows':len(b),'bus_unique_ids':b['정류소아이디'].nunique(),'bus_unique_names':b['정류소명'].nunique(),'bus_extra_rows_at_exact_duplicate_coordinates':int(b.duplicated(['위도','경도']).sum()),'bus_rows_in_coordinate_duplicate_groups':len(co_dup),'bus_blank_service_ids':int(b['서비스아이디'].eq('').sum()),'bus_nonblank_service_id_duplicate_rows':len(service_dup),'bus_blank_directions':int(b['방면'].eq('').sum()),'bus_authority_codes':b['관할관청'].value_counts().to_dict(),'bus_type_codes':b['유형'].value_counts().to_dict(),'literal_virtual_name_stop_rows':int((~not_virtual).sum()),'stations_nearest_literal_virtual_name':int(res['nearest_stop_literal_virtual_name'].sum()),'nearest_distance_changed_by_virtual_exclusion':int((res['nearest_excluding_literal_virtual_name_m']-dist>1e-6).sum()),'same_name_pairs_within_100m':len(pairs),'same_name_groups_with_pair_within_100m':pairs['stop_name'].nunique(),'pairs_with_different_nonblank_direction':int(pairs['different_nonblank_direction'].sum()),'cross_year_unique_station_codes':comparison['station_code'].nunique(),'station_codes_repeated_across_years':int(comparison['year_count'].gt(1).sum()),'first_last_coordinate_shift_over_1m':int(comparison['first_last_coordinate_shift_m'].gt(1).sum())}
    sha={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [SP,BP]}
    text=['# 누비자·버스정류소 공간결합 QA와 기초 접근성 진단','',f'실행 UTC: {datetime.now(timezone.utc).isoformat()}','', '2025년 사용함 454개 거점과 제공된 버스정류소 3,526개 ID 지점 사이 최근접 구면 직선거리와 반경 내 개수를 계산했다. 원본은 변경하지 않았다. 이 결과는 현재 확보한 거점의 연결성을 점검하는 탐색이며 주민의 접근성·교통취약지역 확정 결과가 아니다. 누비자가 없는 지역과 주민·고령인구·일자리의 출발지를 포함하지 않으므로 전체 창원시의 취약성을 판정할 수 없다.','', '## 기준·시점·해석','', '- 누비자 공식 원문: https://www.data.go.kr/data/15000545/fileData.do . 보존한 공식 HTML의 파일데이터명은 20251231, 수정일은 2026-05-26이다. XLSX 시트 2023년/2024년/2025년을 별도 연도 스냅샷으로 처리했다. 사용유무의 실제 텍스트 값은 사용함/사용안함이며 2025년 사용함만 분모에 포함했다. 각 연도의 정확한 일자별 운영 이력은 없다.','- 정류소 공식 원문: https://www.data.go.kr/data/15037805/fileData.do . 보존된 공식 HTML 파일데이터명은 20251231, 수정일은 2026-04-30이다. 누비자2025 시트와 연도 수준은 맞지만 연중 설치/폐쇄 시점이 일치한다는 보장은 없다. 2023·2024 노선을 복원한 결합이 아니다. 두 원본 모두 2026년 10월 현재 운영 상태를 증명하지 않는다.','- 위도·경도 열 이름과 수치 범위를 따라 위도(lat), 경도(lon)의 십진 도 단위로 해석했다. WGS84 계열 좌표라는 작업 가정이며 별도 좌표계 인증 문서로 검증한 것은 아니다. 지구 평균반지름 6,371,008.8m의 haversine 구면거리이며 타원체 측지거리는 아니다.','- 위도[-90,90], 경도[-180,180] 전역 범위와 지역 진단상자 위도[34.9,35.5], 경도[128.3,129.1]를 검사했다. 지역상자는 행정구역 경계 판정이 아니다. 열 순서를 뒤집으면 위도 범위를 벗어나는지 검사했고 m 단위는 적도1도 약111.2km 및 별도 scalar식 3개 표본으로 확인했다.','- 직선거리는 도보 경로거리·시간이 아니다. 건널목·신호·철도·하천·도로분리·실제 출입구·보행통제는 반영하지 않았다. 반경 경계는 <=100/300/500/1000m이며 이 값은 정책 기준을 확정한 것이 아닌 요청된 진단 문턱이다.','- 버스정류소 존재·방향별 ID 개수는 노선수·배차간격·서비스빈도·실제 승하차·환승실적이 아니다. 관할관청 및 유형 코드 정의가 확보되지 않아 임의로 제거하지 않았다. 관할379만 사용한 최근접 거리도 민감도로 제공했다.','- 정류소아이디는3526행 모두 유일하다. 서비스아이디에는 빈값77행 및 비어있지 않은 중복2행이 있어 위치 결합의 유일키로 사용하지 않았다. 구별 분포는 누비자 원본의 구 텍스트를 사용한 것으로 행정경계 폴리곤으로 재판정하지 않았다.',
    '- 동일명칭의 방향별 정류소를 본래 ID로 유지한다. 반경 내 서로 다른 이름 수·좌표 수는 개수 부풀림 확인용 보조값이며 공식 통합 거점 수가 아니다. 동일 이름이라도 멀리 떨어질 수 있고 이름이 달라도 같은 위치일 수 있다. 같은 이름100m 이내 쌍을 따로 저장했다.','- 정류소명에 가상이 포함된 행은 실제 승하차 시설인지 확인되지 않았다. 주 결과는 제공된 모든 ID를 쓰고 가상 문자열 제외 민감도 개수와 거리를 별도 제공했다. 유형1을 가상으로 매핑하지 않았다.','- 같은 터미널번호의 3개 연도 행을 합산하지 않는다. 연도 내부 ID중복0을 확인하고 연도 간 상태 및 좌표 변경은 별도 감사 CSV로 보존했다.','', '## 집계 결과','', '```json',json.dumps(metrics,ensure_ascii=False,indent=2),'```','',summary.to_markdown(index=False),'','## 경로 확인 표본','',f'{len(samples)}개 표본은 구별 최근접 최대·최소, 전체 원거리 상위5, 근거리 중 사거리/하천/항 등 명칭이 있는 후보를 중복 없이 선정했다. 장벽이 실제 존재한다는 판정은 아니며 사람이 지도·현장·적법한 경로 API로 확인할 가설 표본이다. 대표성 있는 확률표본이 아니다. 제안 CSV에 터미널·정류소 양끝 위경도와 ID, 이유를 넣었다. 현재 API는 호출하지 않았다. nearest_nonvirtual_name_ 열은 가상 문자열만 제외한 대체 종점이며 실제 승하차 가능 시설이라고 보증하지 않는다. 원래 최근접이 가상인 표본394 등은 이 대체 종점을 우선 검토한다.','','## 재현 및 산출물','','실행: `python scripts/collection/accessibility_join_qa.py`. Python '+platform.python_version()+', numpy '+np.__version__+', pandas '+pd.__version__+'. 패키지 설치 없음. 전체 거리 행렬454×3526과 연도 내부 ID 유일성, 반경 개수 단조성, 구별 분모 합454, 독립 scalar 거리 일치를 확인했다.','', '원본 SHA256:','```json',json.dumps(sha,ensure_ascii=False,indent=2),'```','', '산출 CSV는 UTF-8 BOM, 소수 거리6자리(m)로 저장했다. 원본의 명칭 문자열을 임의 해독·정규화하지 않았다.','']+['- '+p for p in outputs]
    META.write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2));print(summary.to_string(index=False));print('SAMPLES',samples[['터미널번호','터미널명','구','nearest_stop_straight_m','sample_reason']].to_string(index=False));print('OUTPUT',META)
    
    # Reopen delivered CSVs to verify the serialized deliverables.
    check=pd.read_csv(OUT/'station_2025_active_stop_accessibility.csv')
    check_sample=pd.read_csv(OUT/'proposed_walking_route_samples.csv')
    if not (len(check) == 454 and check['터미널번호'].is_unique): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 141")
    if not (len(check_sample) == 20 and check_sample['터미널번호'].is_unique): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 142")
    if not (not check['nearest_stop_straight_m'].isna().any()): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 143")
    if not (pd.read_csv(OUT / 'district_summary.csv')['active_stations'].sum() == 454): raise ValueError("필수 자료 검증 실패: accessibility_join_qa.py, 기존 줄 144")
    with META.open('a',encoding='utf-8') as f:
        f.write('\n최종 저장 후 CSV 재독검증: 고유 거점454개, 고유 표본20개, 최근접 거리 결측0, 구별 분모합454를 확인했다.\n')
    print('SERIALIZED_OUTPUT_CHECK_OK')


if __name__ == "__main__":
    main()
