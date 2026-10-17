"""Reconcile aggregate CSVs only. Does not scan original trips."""
import pathlib,pandas as pd
root=pathlib.Path(__file__).resolve().parents[2]
p=root/'data/processed/observed_flows'
h=pd.read_csv(p/'hourly_event_counts.csv');w=pd.read_csv(p/'weekday_event_counts.csv')
s=pd.read_csv(p/'station_hour_flows.csv');d=pd.read_csv(p/'district_hour_flows.csv')
b=pd.read_csv(p/'duration_bins.csv');summary=pd.read_csv(p/'trip_summary.csv')
for r in summary.itertuples():
 y=r.file_year;n=r.rows
 for event in ['departure','return']:
  assert int(h[(h.file_year==y)&(h.event==event)].events.sum())==n
  assert int(w[(w.file_year==y)&(w.event==event)].events.sum())==n
 assert int(b[b.file_year==y].trips.sum())==n
 for frame in [s,d]:
  assert int(frame[frame.file_year==y].departures.sum())==n
  assert int(frame[frame.file_year==y]['returns'].sum())==n-r.return_outside_file_year
coverage=pd.read_csv(p/'daily_observation_coverage.csv',keep_default_na=False)
missing=coverage[(coverage.file_year==2025)&(coverage.event=='departure')&(coverage.observation_status=='no_observations')]
assert len(missing)==31 and missing.date.str.startswith('2025-07-').all()
assert missing.events.eq('').all()
print('Aggregate reconciliation and missing July distinction: PASS')
