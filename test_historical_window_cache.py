"""Bounded storage, source invalidation, output equivalence and gate admission."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask, jsonify
from historical_window_cache import WindowCache, WINDOWS, MAX_BYTES, MAX_ENTRY_BYTES, window_context
from hosted_memory import install_memory_gate


class WindowCacheTests(unittest.TestCase):
    def context(self):
        return {'games':[{'rank':1,'ranking_score':51.2,'ranking_trend':{'ats_rate':61.0},
                          'top_trends':[{'spread':'0.5-3'}], 'matches':['unneeded data']}], 'pending':[]}

    def test_replacement_copy_isolation_source_changes_and_minute_expiry(self):
        cache=WindowCache(); context=self.context()
        self.assertTrue(cache.put(('5',False),'source1',context,now=61))
        cached=cache.get(('5',False),'source1',now=62)
        self.assertNotIn('matches',cached['games'][0])
        self.assertEqual(cached['games'][0]['ranking_score'],51.2)
        cached['games'][0]['rank']=99
        self.assertEqual(cache.get(('5',False),'source1',now=63)['games'][0]['rank'],1)
        size=cache.bytes
        cache.put(('5',False),'source1',context,now=64)
        self.assertEqual(cache.bytes,size)
        self.assertIsNone(cache.get(('5',False),'source2',now=65))
        self.assertEqual(cache.bytes,0)
        cache.put(('5',False),'source2',context,now=119)
        self.assertIsNone(cache.get(('5',False),'source2',now=120))
        self.assertEqual(cache.bytes,0)

    def test_all_ten_keys_and_total_byte_bound(self):
        cache=WindowCache()
        for window in WINDOWS:
            for archive in (False,True):
                cache.put((window,archive),'source',self.context(),now=60)
        self.assertEqual(len(cache.entries),10)
        for window in WINDOWS:
            for archive in (False,True):
                cache.put((window,archive),'source',{'games':[{'name':'x'*130000}],'pending':[]},now=60)
                self.assertLessEqual(cache.bytes,MAX_BYTES)
                self.assertLessEqual(len(cache.entries),10)
        self.assertEqual(cache.bytes,sum(len(entry[2]) for entry in cache.entries.values()))

    def test_oversized_invalid_and_non_json_entries_are_not_retained(self):
        cache=WindowCache()
        self.assertFalse(cache.put(('5',False),'source',{'games':[{'name':'x'*MAX_ENTRY_BYTES}]},now=60))
        self.assertFalse(cache.put(('bad',False),'source',self.context(),now=60))
        self.assertFalse(cache.put(('5',False),'source',{'games':[{'value':float('nan')}]},now=60))
        self.assertFalse(cache.put(('5',False),'source',{'games':[{'value':object()}]},now=60))
        self.assertEqual(cache.bytes,0)

    def make_app(self):
        app=Flask(__name__)
        app.config['TESTING']=True
        calls=[]
        entered,release=threading.Event(),threading.Event()
        @app.get('/sunday',endpoint='sunday_page')
        def sunday():
            def build():
                calls.append(True)
                return {'games':[{'rank':1}],'pending':[]}
            return jsonify(window_context(build))
        @app.get('/slow')
        def slow():
            entered.set(); release.wait(4)
            return 'heavy report'
        install_memory_gate(app)
        return app,calls,entered,release

    def test_cached_window_bypasses_busy_gate_but_changed_sources_do_not(self):
        app,calls,entered,release=self.make_app()
        with patch('historical_window_cache.source_signature',return_value='source1'):
            expected=app.test_client().get('/sunday?window=5').data
            def heavy():
                with app.test_client() as client:
                    return client.get('/slow').status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                running=pool.submit(heavy)
                try:
                    self.assertTrue(entered.wait(1))
                    response=app.test_client().get('/sunday?window=5')
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(response.data,expected)
                    self.assertEqual(len(calls),1)
                    with patch('historical_window_cache.source_signature',return_value='changed'):
                        self.assertEqual(app.test_client().get('/sunday?window=5').status_code,503)
                    self.assertEqual(len(calls),1)
                finally:
                    release.set()
                self.assertEqual(running.result(timeout=2),200)

    def test_signature_change_or_minute_boundary_during_build_is_not_cached(self):
        from historical_window_cache import cache
        app=Flask(__name__)
        for time_values,signatures in [([61,61,120],['a','a']),([61,61,61],['a','b'])]:
            app.extensions.clear()
            with app.test_request_context('/sunday?window=5'), patch('historical_window_cache.time',side_effect=time_values), patch('historical_window_cache.source_signature',side_effect=signatures):
                context=window_context(lambda:{'games':[],'pending':[]})
                self.assertEqual(context['games'],[])
                self.assertEqual(cache().bytes,0)

    def test_actual_source_signature_has_no_network_and_tracks_file_changes(self):
        import tempfile
        from pathlib import Path
        from historical_window_cache import source_signature
        app=Flask(__name__)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'nfl_games.csv'; path.write_text('fixture')
            with app.test_request_context('/sunday'), patch('trend_finder_2.game_file',path), patch('fan_views.urlopen',side_effect=AssertionError('Cache checked network')):
                before=source_signature()
                (Path(folder)/'manual_spread_overrides.csv').write_text('new line')
                self.assertNotEqual(before,source_signature())


if __name__=='__main__':
    unittest.main()
