import importlib.util, pathlib, tempfile, unittest
from unittest.mock import patch
MODULE=pathlib.Path(__file__).with_name('collect_approved_public_apis.py')
class PublicApiSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('collector',MODULE)
        cls.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.m)
    def test_encoded_key_is_decoded_once_without_plus_translation(self):
        self.assertEqual(self.m.normalize_key('ab%2Bc%2F%3D'),'ab+c/=')
        self.assertEqual(self.m.normalize_key('ab+c/='),'ab+c/=')
    def test_missing_key_does_not_request_network(self):
        with tempfile.TemporaryDirectory() as d,patch('urllib.request.urlopen') as network:
            self.assertEqual(self.m.load_key(pathlib.Path(d)/'.env.local'),'')
            network.assert_not_called()
    def test_main_without_key_exits_before_collector_or_network(self):
        with patch.object(self.m,'load_key',return_value=''),patch.object(self.m,'Collector') as collector,patch('urllib.request.urlopen') as network,patch('builtins.print'):
            self.assertEqual(self.m.main([]),2)
            collector.assert_not_called();network.assert_not_called()
    def test_error_header_is_not_http_success(self):
        with self.assertRaises(self.m.CollectionError):
            self.m.parse_payload({'response':{'header':{'resultCode':'30','resultMsg':'bad key'}}})
    def test_single_item_and_empty_normalization(self):
        head={'resultCode':'00'}
        self.assertEqual(self.m.parse_payload({'response':{'header':head,'body':{'totalCount':1,'items':{'item':{'nodeid':'one'}}}}})[0],[{'nodeid':'one'}])
        self.assertEqual(self.m.parse_payload({'response':{'header':head,'body':{'totalCount':0,'items':''}}})[0],[])
    def test_pagination_mismatch_rejected(self):
        with self.assertRaises(self.m.CollectionError):
            self.m.validate_page({'pageNo':2},1,10,10,None)
    def test_daily_coverage_reports_holes_and_duplicates(self):
        report=self.m.daily_coverage([{'tm':'2023-01-01','stnId':'155'},{'tm':'2023-01-01','stnId':'155'}],2023)
        self.assertEqual(report['expected_days'],365)
        self.assertEqual(report['duplicate_dates'],1)
        self.assertEqual(len(report['missing_dates']),364)
if __name__=='__main__':unittest.main()

