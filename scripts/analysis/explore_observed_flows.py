"""Single-pass descriptive aggregates of completed 2024/2025 Nubija trips only."""
from __future__ import annotations
import collections,datetime as dt,hashlib,json,math,pathlib,sys,time
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'data/processed/observed_flows'
COLUMNS=['자전거번호','출발터미널','출발일','출발시간','도착터미널','도착일','도착시간']
BINS=[-float('inf'),-0.0001,0,300,900,1800,3600,7200,86400,604800,2592000,float('inf')]
LABELS=['negative','zero','positive_to_5min','over_5_to_15min','over_15_to_30min','over_30_to_60min','over_1_to_2h','over_2_to_24h','over_24h_to_7d','over_7d_to_30d','over_30d']
SOURCE_HASH={2024:'8146617ccfa69430cfbb4c570b750df9456667dd72cba374b4396cee34e3a51f',2025:'e4b269df2bf018095f358eb56067464c6554fb41713ad1cd9a5765affb3606dc'}

def new_state(year):
 return {'year':year,'counts':collections.Counter(),'events':collections.Counter(),'station_hours':collections.Counter(),'durations':collections.Counter(),'seconds_hist':collections.Counter(),'unknown':{'departure':collections.Counter(),'return':collections.Counter()}}

def duration_bucket(seconds):
 if seconds<0:return 'negative'
 if seconds==0:return 'zero'
 for edge,label in zip(BINS[3:],LABELS[2:]):
  if seconds<=edge:return label

def calendar_rows(year,direction,days):
 first=dt.date(year,1,1);n=(dt.date(year+1,1,1)-first).days
 return [{'file_year':year,'event':direction,'date':(date:=first+dt.timedelta(days=i)).isoformat(),'weekday':date.weekday(),'events':days.get(date.isoformat(),''),'observation_status':'observed_date' if date.isoformat() in days else 'no_observations'} for i in range(n)]

def consume(chunk,state,known_codes=None):
 if list(chunk.columns)!=COLUMNS:raise ValueError('Original seven-column schema mismatch')
 year=state['year'];counts=state['counts'];counts['rows']+=len(chunk)
 start=pd.to_datetime(chunk['출발일']+' '+chunk['출발시간'],format='%Y-%m-%d %H:%M:%S',errors='coerce')
 end=pd.to_datetime(chunk['도착일']+' '+chunk['도착시간'],format='%Y-%m-%d %H:%M:%S',errors='coerce')
 counts['invalid_departure_datetime']+=int(start.isna().sum());counts['invalid_return_datetime']+=int(end.isna().sum())
 sec=(end-start).dt.total_seconds()
 counts['zero_seconds']+=int(sec.eq(0).sum());counts['negative_seconds']+=int(sec.lt(0).sum())
 same=chunk['출발터미널'].eq(chunk['도착터미널'])
 counts['same_station']+=int(same.sum());counts['same_station_zero_seconds']+=int((same&sec.eq(0)).sum())
 counts['return_outside_file_year']+=int((end.notna()&end.dt.year.ne(year)).sum())
 counts['departure_outside_file_year']+=int((start.notna()&start.dt.year.ne(year)).sum())
 counts['cross_calendar_day']+=int((start.notna()&end.notna()&start.dt.date.ne(end.dt.date)).sum())
 state['seconds_hist'].update({float(k):int(v) for k,v in sec.dropna().value_counts().items()})
 state['durations'].update({str(k):int(v) for k,v in pd.cut(sec,bins=BINS,labels=LABELS,right=True).value_counts(sort=False).items()})
 for direction,times,column in [('departure',start,'출발터미널'),('return',end,'도착터미널')]:
  valid=times.notna();t=times[valid]
  frame=pd.DataFrame({'date':t.dt.strftime('%Y-%m-%d'),'hour':t.dt.hour,'station':chunk.loc[valid,column]})
  for (date,hour),n in frame.groupby(['date','hour'],sort=False).size().items():state['events'][(direction,date,int(hour))]+=int(n)
  within=t.dt.year.eq(year)
  for (station,hour),n in frame.loc[within].groupby(['station','hour'],sort=False).size().items():state['station_hours'][(direction,str(station),int(hour))]+=int(n)
  if known_codes is not None:state['unknown'][direction].update(chunk.loc[~chunk[column].isin(known_codes),column].value_counts().to_dict())

def quantile(hist,q):
 n=sum(hist.values());target=math.ceil(n*q);acc=0
 for value,count in sorted(hist.items()):
  acc+=count
  if acc>=target:return value
 return None

def save(name,rows):
 path=OUT/name;pd.DataFrame(rows).to_csv(path,index=False,encoding='utf-8-sig')
 raw=path.read_bytes()
 return {'file':str(path.relative_to(ROOT)),'rows':len(rows),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 stations_path=ROOT/'data/raw/nubija_stations/nubija_stations_2023_2025.xlsx'
 summaries=[];daily=[];monthly=[];hourly=[];weekdays=[];station_hour=[];district_hour=[];duration=[];unknown=[]
 for year in [2024,2025]:
  ref=pd.read_excel(stations_path,sheet_name=f'{year}년',dtype={'터미널번호':str})
  ref['터미널번호']=ref['터미널번호'].str.strip()
  if ref['터미널번호'].duplicated().any():raise ValueError('Station reference duplicate codes')
  districts=dict(zip(ref['터미널번호'],ref['구'].astype(str)));known=set(districts)
  state=new_state(year);source=ROOT/f'data/raw/nubija_trips/nubija_trips_{year}.csv'
  before=source.stat();began=time.monotonic()
  # Each completed original CSV is scanned once; no other year or raw sample is exported.
  for chunk in pd.read_csv(source,encoding='cp949',dtype=str,keep_default_na=False,chunksize=150000):consume(chunk,state,known)
  after=source.stat()
  if before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns:raise ValueError('Source changed during scan')
  counts=state['counts'];n=counts['rows'];hist=state['seconds_hist']
  summary={'file_year':year,**dict(counts),'same_station_share':counts['same_station']/n,'zero_seconds_share':counts['zero_seconds']/n,'duration_median_seconds_nearest_rank':quantile(hist,.5),'duration_p90_seconds_nearest_rank':quantile(hist,.9),'duration_p95_seconds_nearest_rank':quantile(hist,.95),'duration_max_seconds':max(hist) if hist else None,'source_bytes':before.st_size,'source_sha256_previously_verified':SOURCE_HASH[year],'scan_seconds':round(time.monotonic()-began,3)}
  for label in LABELS:duration.append({'file_year':year,'duration_bin':label,'trips':state['durations'][label],'share_of_all_rows':state['durations'][label]/n})
  for direction in ['departure','return']:
   event_counter=collections.Counter({(date,hour):v for (d,date,hour),v in state['events'].items() if d==direction})
   day_counts=collections.Counter()
   for (date,hour),v in event_counter.items():day_counts[date]+=v
   daily.extend(calendar_rows(year,direction,day_counts))
   # Preserve spillover return date attribution in an explicit extra-year table row.
   for date,v in sorted(day_counts.items()):
    if not date.startswith(str(year)+'-'):daily.append({'file_year':year,'event':direction,'date':date,'weekday':dt.date.fromisoformat(date).weekday(),'events':v,'observation_status':'observed_spillover_date'})
   actual_years=sorted({int(date[:4]) for date in day_counts}|{year})
   for actual_year in actual_years:
    selected={d:v for d,v in day_counts.items() if d.startswith(str(actual_year)+'-')}
    n_days=len(selected)
    for h in range(24):
     count=sum(v for (date,hour),v in event_counter.items() if hour==h and date.startswith(str(actual_year)+'-'))
     hourly.append({'file_year':year,'event':direction,'event_calendar_year':actual_year,'hour':h,'events':count,'observed_dates':n_days,'events_per_observed_date':count/n_days if n_days else ''})
    for weekday in range(7):
     subset={d:v for d,v in selected.items() if dt.date.fromisoformat(d).weekday()==weekday}
     weekdays.append({'file_year':year,'event':direction,'event_calendar_year':actual_year,'weekday_monday0':weekday,'events':sum(subset.values()),'observed_dates':len(subset),'events_per_observed_date':sum(subset.values())/len(subset) if subset else ''})
    for month in range(1,13):
     prefix=f'{actual_year}-{month:02d}';subset={d:v for d,v in selected.items() if d.startswith(prefix)}
     if actual_year!=year and not subset:continue
     monthly.append({'file_year':year,'event':direction,'event_month':prefix,'events':sum(subset.values()) if subset else '', 'observed_dates':len(subset),'calendar_days':(dt.date(actual_year+int(month==12),month%12+1,1)-dt.date(actual_year,month,1)).days,'events_per_observed_date':sum(subset.values())/len(subset) if subset else '', 'observation_status':'observed_dates_present' if subset else 'no_observations'})
   summary[f'{direction}_observed_dates_in_file_year']=sum(d.startswith(str(year)+'-') for d in day_counts)
   summary[f'{direction}_missing_dates_in_file_year']=[r['date'] for r in calendar_rows(year,direction,day_counts) if r['observation_status']=='no_observations']
   for code,v in state['unknown'][direction].items():unknown.append({'file_year':year,'event':direction,'station_code':code,'events':v,'reference_sheet':f'{year}년'})
  station_codes={code for direction,code,h in state['station_hours']}
  dist=collections.Counter()
  for code in sorted(station_codes,key=lambda x:(not x.isdigit(),int(x) if x.isdigit() else x)):
   for hour in range(24):
    departures=state['station_hours'][('departure',code,hour)];returns=state['station_hours'][('return',code,hour)]
    district=districts.get(code,'UNMATCHED')
    station_hour.append({'file_year':year,'event_calendar_year':year,'station_code':code,'reference_district':district,'hour':hour,'departures':departures,'returns':returns,'net_outflow_departures_minus_returns':departures-returns,'reference_matched':code in known})
    dist[(district,hour,'departure')]+=departures;dist[(district,hour,'return')]+=returns
  for district in sorted({x[0] for x in dist}):
   for hour in range(24):
    dep=dist[(district,hour,'departure')];ret=dist[(district,hour,'return')]
    district_hour.append({'file_year':year,'event_calendar_year':year,'reference_district':district,'hour':hour,'departures':dep,'returns':ret,'net_outflow_departures_minus_returns':dep-ret})
  summaries.append(summary)
  print(f'{year}: aggregated {n:,} rows in {summary["scan_seconds"]} seconds',flush=True)
 files=[]
 for name,rows in [('daily_observation_coverage.csv',daily),('monthly_event_counts.csv',monthly),('hourly_event_counts.csv',hourly),('weekday_event_counts.csv',weekdays),('station_hour_flows.csv',station_hour),('district_hour_flows.csv',district_hour),('duration_bins.csv',duration),('trip_summary.csv',summaries),('unmatched_station_codes.csv',unknown)]:files.append(save(name,rows))
 result={'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'summary':summaries,'output_files':files,'source_hash_note':'Existing verified hashes from data/metadata/nubija_trips.md; raw CSV not read again for hashing.','python':sys.version,'pandas':pd.__version__}
 (ROOT/'data/metadata/observed_flows_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
