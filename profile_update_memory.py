"""Offline memory benchmark. No network, production updates, or live forecasts.

Uses disposable site/data copies, wide synthetic stats, and the existing fixed
clock model fixture padded with real local historical schedule/market volumes.
Run with .venv/bin/python profile_update_memory.py. Results are platform-specific.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent


def case(name, folder):
    from unittest.mock import patch
    if name in ('website','website_concurrent','website_guarded'):
        site = folder/'site'
        os.chdir(site)
        sys.path.insert(0, str(site))
        import app
        app.app.config['TESTING'] = True
        if name == 'website_guarded':
            from hosted_memory import install_memory_gate
            install_memory_gate(app.app)
        from trend_finder_2 import scan_basic_trends
        scan_basic_trends(season='2026')
        scan_basic_trends(season=(1999, 2025))
        with app.app.test_client() as client:
            assert client.get('/').status_code == 200
            response = client.get('/conspiracy-dungeon?panel=movement')
            assert response.status_code == 200, (response.status_code, response.data[:500])
        if name in ('website_concurrent','website_guarded'):
            from concurrent.futures import ThreadPoolExecutor
            def request(index):
                import time
                for attempt in range(8):
                    with app.app.test_client() as client:
                        response = client.get('/' if index % 2 else '/conspiracy-dungeon?panel=movement')
                        if response.status_code != 503: return response.status_code
                        assert response.headers.get('Retry-After') == '1'
                    time.sleep(1)
                raise RuntimeError('Analytics remained saturated through eight retries')
            with ThreadPoolExecutor(max_workers=4) as pool:
                assert list(pool.map(request, range(8))) == [200]*8
            if os.environ.get('PROFILE_MEMORY_HOLD') == '1':
                import threading
                stop = threading.Event()
                def traffic(index):
                    while not stop.is_set():
                        assert request(index) == 200
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(traffic, i) for i in range(4)]
                    print('MEMORY_READY', flush=True)
                    sys.stdin.read()
                    stop.set()
                    for future in futures:
                        future.result(timeout=30)
    elif name in ('collect_baseline', 'collect_optimized'):
        import polars as pl
        import nflreadpy as nfl
        import scout4.collect as collector
        if name.endswith('baseline'):
            import hosted_updates, fan_views, scheduled_ats_capture, prediction_staging
            # Committed pre-optimization function, retained in this offline fixture.
            namespace = {'__name__':'scout4.collect_baseline', '__package__':'scout4',
                         '__file__':str(SOURCE/'scout4/collect.py')}
            exec((folder/'baseline_collect.py').read_text(), namespace)
            collect = namespace['collect']
        else:
            collect = collector.collect
        with patch.object(nfl, 'load_team_stats', side_effect=lambda *a, **k:pl.read_parquet(folder/'team.parquet')), \
             patch.object(nfl, 'load_player_stats', side_effect=lambda *a, **k:pl.read_parquet(folder/'player.parquet')):
            collect(2026, folder/name)
    elif name in ('model_direct', 'model_staged'):
        from test_prediction_staging import NOW, FixedClock
        from scout4 import shadow
        root = folder/name
        with patch.object(shadow, 'datetime', FixedClock), patch('plug_publication.clock', return_value=NOW):
            if name == 'model_direct':
                from scout4 import blend
                with patch.dict(os.environ, {'TREND_FINDAH_AUTO_MODEL_CONFIG':str(root/'automatic_model.json')}):
                    assert blend.run(root, now=NOW)['saved'] == 13
            else:
                from prediction_staging import run_staged
                run_staged(root, SOURCE, SOURCE/'automatic_model.json', clock=lambda:NOW)
    elif name == 'supervisor':
        import hosted_updates
        import qb_verification
        if os.environ.get('PROFILE_MEMORY_HOLD') == '1':
            print('MEMORY_READY', flush=True)
            sys.stdin.read()
    elif name == 'schedule_replay':
        import nflreadpy
        import polars as pl
        # Local replay of full-history download/filter/to_dicts shape; no HTTP.
        frame = pl.read_csv(SOURCE/'nfl_games.csv', infer_schema=False)
        rows = frame.filter(pl.col('season') == '2026').to_dicts()
        assert rows
    elif name == 'quotes_replay':
        from collect_ats_handle import parse_page
        from public_money import parse_markets
        files = list((SOURCE/'logs/ats_handle').glob('*.html'))
        if not files:
            raise ValueError('No archived quote page available for offline replay')
        raw = max(files, key=lambda p:p.stat().st_size).read_bytes()
        html = raw.decode('utf-8')
        ats = list(parse_page(html))
        markets = parse_markets(html)
        assert ats and markets
    elif name == 'publication_grading':
        from test_prediction_staging import NOW
        import plug_publication
        from fan_views import prediction_performance
        from scout4.stats import read_csv
        root = folder/'model_staged'
        with patch('plug_publication.clock', return_value=NOW):
            plug_publication.publish(root, folder/'expert', SOURCE/'automatic_model.json')
        records = [json.loads(p.read_text()) for p in (root/'data/scout4/blend/predictions').glob('*.json')]
        prediction_performance(records, read_csv(root/'nfl_games.csv'))
    else:
        raise ValueError(name)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != 'darwin':
        peak *= 1024
    print('MEMORY_RESULT '+json.dumps({'case':name, 'peak_MiB':round(peak/1048576, 2)}))


def benchmark(folder):
    import csv
    import polars as pl
    from scout4.stats import TEAM_METRICS, PLAYER_METRICS
    from test_prediction_staging import fixture, csv_file
    # Baseline comes from the deployed commit, never from a modified model.
    baseline = subprocess.check_output(['git','show','3b48687:scout4/collect.py'], cwd=SOURCE)
    (folder/'baseline_collect.py').write_bytes(baseline)
    identity = ['season','week','season_type','game_id','team','opponent_team']
    for kind, rows, metrics in [('team',600,TEAM_METRICS), ('player',25000,PLAYER_METRICS)]:
        fields = identity + (['player_id','player_name','player_display_name','position'] if kind=='player' else [])
        values = {key:['2026' if key=='season' else 'fixture']*rows for key in fields}
        values.update({key:[1.125]*rows for key in metrics})
        values.update({f'unused_{i}':[float(i)]*rows for i in range(100)})
        pl.DataFrame(values).write_parquet(folder/(kind+'.parquet'))
    for name in ('model_direct','model_staged'):
        root = folder/name
        fixture(root)
        # Thirteen eligible games with three completed weeks per team, keeping
        # all timestamps and approved calculation functions fixed.
        import hashlib
        from scout4.stats import read_csv
        seeds = read_csv(root/'nfl_games.csv')
        feed = read_csv(root/'data/scout4/fixture/team.csv')
        quotes = read_csv(root/'public_money_snapshots.csv')
        teams = ['NE','BUF','NYJ','MIA','KC','DEN','LV','LAC','PIT','BAL','CLE','CIN',
                 'HOU','IND','TEN','JAX','DAL','NYG','PHI','WAS','GB','CHI','DET','MIN','ATL','NO']
        schedule, statistics, markets = [], [], []
        for away, home in zip(teams[::2], teams[1::2]):
            for game in seeds:
                schedule.append({**game, 'game_id':f'2030_{int(game["week"]):02}_{away}_{home}',
                                 'away_team':away, 'home_team':home})
            for row in feed:
                team, opponent = (away,home) if row['team']=='NE' else (home,away)
                statistics.append({**row, 'game_id':f'2030_{int(row["week"]):02}_{away}_{home}',
                                   'team':team, 'opponent_team':opponent})
            for row in quotes:
                markets.append({**row, 'game_id':f'2030_04_{away}_{home}', 'away_team':away, 'home_team':home,
                    'side_a':away if row['market']=='Spread' else row['side_a'],
                    'side_b':home if row['market']=='Spread' else row['side_b']})
        csv_file(root/'nfl_games.csv', schedule)
        csv_file(root/'public_money_snapshots.csv', markets)
        team_path = root/'data/scout4/fixture/team.csv'
        csv_file(team_path, statistics)
        manifest_path = root/'data/scout4/2030/latest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files']['team']['sha256'] = hashlib.sha256(team_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        for filename in ('nfl_games.csv','public_money_snapshots.csv'):
            with (root/filename).open(newline='') as stream:
                required = list(csv.DictReader(stream))
            with (SOURCE/filename).open(newline='', encoding='utf-8-sig') as stream:
                historical = list(csv.DictReader(stream))
            fields = list(dict.fromkeys(k for row in required+historical[:1] for k in row))
            csv_file(root/filename, [{k:row.get(k,'') for k in fields} for row in historical+required])
    site = folder/'site'
    site.mkdir()
    for path in SOURCE.glob('*.py'):
        shutil.copyfile(path, site/path.name)
    shutil.copytree(SOURCE/'scout4', site/'scout4', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('nfl_games.csv','public_money_snapshots.csv','ats_handle_snapshots.csv','automatic_model.json'):
        shutil.copyfile(SOURCE/name, site/name)
    # Benchmark deployed templates; unrelated work-in-progress templates may be
    # edited concurrently. Assets are read only by this Flask test client.
    paths = subprocess.check_output(['git','ls-tree','-r','--name-only','3b48687','templates'], cwd=SOURCE, text=True)
    for relative in paths.splitlines():
        target = site/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','show','3b48687:'+relative], cwd=SOURCE))
    (site/'static').symlink_to(SOURCE/'static', target_is_directory=True)
    environment = {**os.environ, 'POLARS_MAX_THREADS':'1', 'TREND_FINDAH_AUTO_UPDATE':'0',
        'TREND_FINDAH_ENV':'development', 'TREND_FINDAH_DATABASE':str(site/'members.sqlite3'),
        'TREND_FINDAH_SECRET_KEY':'offline-memory-fixture',
        'TREND_FINDAH_EXPERT_STORE':str(site/'expert'),
        'TREND_FINDAH_EXPERT_AUTO_DRAFT':'0', 'TREND_FINDAH_EXPERT_AUTO_PUBLISH':'0'}
    results = []
    for name in ('supervisor','schedule_replay','collect_baseline','collect_optimized','quotes_replay',
                 'model_direct','model_staged','publication_grading','website','website_concurrent','website_guarded'):
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--case',name,'--folder',str(folder)],
                               capture_output=True, text=True, env=environment, timeout=180)
        if child.returncode:
            raise RuntimeError(name+': '+child.stderr[-2500:])
        result = json.loads(next(line.removeprefix('MEMORY_RESULT ') for line in child.stdout.splitlines()
                                 if line.startswith('MEMORY_RESULT ')))
        results.append(result)
        print(json.dumps(result), flush=True)
    relative = 'data/scout4/blend/predictions'
    direct = {p.name:p.read_bytes() for p in (folder/'model_direct'/relative).glob('*.json')}
    staged = {p.name:p.read_bytes() for p in (folder/'model_staged'/relative).glob('*.json')}
    assert len(direct) == 13 and direct == staged
    for kind in ('team','player'):
        a = next((folder/'collect_baseline').glob('2026/*/'+kind+'.csv'))
        b = next((folder/'collect_optimized').glob('2026/*/'+kind+'.csv'))
        assert a.read_bytes() == b.read_bytes(), kind
    print('EQUIVALENCE: all 13 forecast files and team/player CSV bytes identical', flush=True)
    peaks = {r['case']:r['peak_MiB'] for r in results}
    print(json.dumps({'case':'combined_peak_budget', 'method':'sum of separate measured peaks; excludes master/OS',
        'baseline_MiB':round(peaks['website_concurrent']+peaks['collect_baseline'],2),
        'optimized_MiB':round(peaks['website_guarded']+peaks['supervisor']+peaks['collect_optimized'],2)}), flush=True)
    # Sample live RSS sums while four website clients contend with the feed.
    # This excludes the benchmark harness and is not a Linux cgroup measurement.
    import time
    for mode, website, feed in [('baseline','website_concurrent','collect_baseline'),
                               ('optimized','website_guarded','collect_optimized')]:
        held = []
        child = None
        try:
            for name in [website]+(['supervisor'] if mode=='optimized' else []):
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--case',name,'--folder',str(folder)],
                    env={**environment,'PROFILE_MEMORY_HOLD':'1'}, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                held.append(process)
                while True:
                    line = process.stdout.readline()
                    if line.startswith('MEMORY_READY'): break
                    if not line: raise RuntimeError(process.stderr.read()[-1500:])
            # New output directory for the replay, leaving earlier comparisons intact.
            shutil.rmtree(folder/feed)
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--case',feed,'--folder',str(folder)],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            peak = 0
            while child.poll() is None:
                try:
                    listing = subprocess.check_output(['ps','-o','rss=','-p',','.join(str(p.pid) for p in held+[child])], text=True)
                except PermissionError:
                    print('Combined RSS sampling unavailable: process inspection denied by this session.', flush=True)
                    return results
                peak = max(peak, sum(int(value) for value in listing.split())/1024)
                time.sleep(.02)
            output, error = child.communicate()
            if child.returncode: raise RuntimeError(error[-1500:])
            print(json.dumps({'case':'combined_'+mode, 'sampled_peak_RSS_MiB':round(peak,2)}), flush=True)
        finally:
            if child is not None and child.poll() is None:
                child.kill(); child.communicate()
            for process in held:
                output, error = process.communicate(timeout=60)
                if process.returncode: raise RuntimeError(error[-1500:])
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case')
    parser.add_argument('--folder', type=Path)
    args = parser.parse_args()
    if args.case:
        case(args.case, args.folder)
    else:
        with tempfile.TemporaryDirectory(prefix='scout-memory-') as directory:
            benchmark(Path(directory))
