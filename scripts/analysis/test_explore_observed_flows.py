import importlib.util,pathlib,unittest
import pandas as pd
P=pathlib.Path(__file__).with_name('explore_observed_flows.py')
class FlowTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  s=importlib.util.spec_from_file_location('flows',P);cls.m=importlib.util.module_from_spec(s);s.loader.exec_module(cls.m)
 def test_boundary_return_and_same_station_zero_are_separate(self):
  rows=[['a','1','2024-12-31','23:50:00','2','2025-01-01','00:10:00'],['b','1','2024-12-31','23:55:00','1','2024-12-31','23:55:00']]
  state=self.m.new_state(2024)
  self.m.consume(pd.DataFrame(rows,columns=self.m.COLUMNS),state)
  self.assertEqual(state['counts']['rows'],2)
  self.assertEqual(state['counts']['return_outside_file_year'],1)
  self.assertEqual(state['counts']['same_station'],1)
  self.assertEqual(state['counts']['zero_seconds'],1)
  self.assertEqual(state['events'][('return','2025-01-01',0)],1)
 def test_missing_days_are_not_zero_demand(self):
  rows=self.m.calendar_rows(2024,'departure',{'2024-01-01':2})
  self.assertEqual(len(rows),366)
  self.assertEqual(rows[1]['observation_status'],'no_observations')
  self.assertEqual(rows[1]['events'],'')
 def test_positive_duration_bucket_boundaries(self):
  self.assertEqual(self.m.duration_bucket(300),'positive_to_5min')
  self.assertEqual(self.m.duration_bucket(301),'over_5_to_15min')
if __name__=='__main__':unittest.main()
