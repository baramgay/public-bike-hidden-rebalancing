"""Network-free regression tests for the reviewed collection scripts."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT/'scripts/collection'
NAMES = ['nubija_trips_collect.py','nubija_trips_collect_2025.py','nubija_trips_validate.py','nubija_trips_quality_2025.py','stations_transit_collect.py','stations_transit_verify.py','accessibility_facilities_verify.py','award_cases_collect.py','accessibility_join_qa.py']
COLLECTORS = ['nubija_trips_collect.py','nubija_trips_collect_2025.py','stations_transit_collect.py','award_cases_collect.py']


def load(name):
    spec=importlib.util.spec_from_file_location('review_'+name.replace('.','_'),COLLECTION/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class Response:
    def __init__(self,body,length=None):
        self.body=body;self.headers={'Content-Length':str(len(body) if length is None else length)}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def raise_for_status(self):pass
    def iter_content(self,size):yield self.body


class ReproducibilityTests(unittest.TestCase):
    def test_import_has_no_network_or_writes(self):
        with patch.object(requests,'get',side_effect=AssertionError('network forbidden')),patch.object(Path,'mkdir',side_effect=AssertionError('mkdir on import')),patch.object(Path,'write_text',side_effect=AssertionError('write on import')),patch.object(Path,'write_bytes',side_effect=AssertionError('write on import')):
            for name in NAMES:
                with self.subTest(script=name):load(name)

    def test_existing_file_is_not_overwritten_or_requested(self):
        for name in COLLECTORS:
            with self.subTest(script=name),tempfile.TemporaryDirectory() as tmp:
                m=load(name);target=Path(tmp)/'source.csv';body=b'a,b\n1,2\n';target.write_bytes(body)
                with patch.object(requests,'get',side_effect=AssertionError('network forbidden')):
                    self.assertEqual(m.download('https://invalid.example',target,'csv')['state'],'skipped_existing')
                self.assertEqual(target.read_bytes(),body)

    def test_short_transfer_and_html_never_promoted(self):
        for name in COLLECTORS:
            for body,length in [(b'a,b\n1,2\n',999),(b'<html>error</html>',None)]:
                with self.subTest(script=name,body=body),tempfile.TemporaryDirectory() as tmp:
                    m=load(name);target=Path(tmp)/'source.csv'
                    with patch.object(requests,'get',return_value=Response(body,length)):
                        with self.assertRaises(ValueError):m.download('https://invalid.example',target,'csv')
                    self.assertFalse(target.exists());self.assertTrue(target.with_name(target.name+'.partial').exists())

    def test_complete_transfer_promoted_and_partial_preserved(self):
        m=load('nubija_trips_collect_2025.py')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source.csv';body=b'a,b\n1,2\n'
            with patch.object(requests,'get',return_value=Response(body)):
                self.assertEqual(m.download('https://invalid.example',p,'csv')['state'],'complete')
            self.assertEqual(p.read_bytes(),body);self.assertFalse(p.with_name(p.name+'.partial').exists())
            q=Path(tmp)/'blocked.csv';partial=q.with_name(q.name+'.partial');partial.write_bytes(b'keep')
            with patch.object(requests,'get',side_effect=AssertionError('network forbidden')):
                with self.assertRaises(FileExistsError):m.download('https://invalid.example',q,'csv')
            self.assertEqual(partial.read_bytes(),b'keep')

    def test_failed_collectors_return_nonzero(self):
        for name in COLLECTORS:
            with self.subTest(script=name),tempfile.TemporaryDirectory() as tmp:
                m=load(name);m.ROOT=Path(tmp)
                with patch.object(m,'download',side_effect=ValueError('mock failure')),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(m.main(),1)

    def test_2022_not_default_and_no_wait(self):
        m=load('nubija_trips_collect.py');self.assertEqual([x[0] for x in m.ITEMS],[2024,2023])
        source=(COLLECTION/'nubija_trips_validate.py').read_text(encoding='utf-8')
        self.assertNotIn('time.sleep',source);self.assertNotIn('1800',source)


if __name__=='__main__':unittest.main()
