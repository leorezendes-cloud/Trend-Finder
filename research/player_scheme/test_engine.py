import copy,csv,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .store import connect,ingest,history,maintain,LIMIT
from .features import build,rate
from .evaluate import Ridge,evaluate

CAP='2024-09-02T00:00:00+00:00'
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.db=connect(self.root/'research.sqlite');self.addCleanup(self.db.close)
        self.schedule=[];self.teams=[];self.players=[]
        for w in range(1,9):
            gid=f'2024_{w:02}_NE_BUF';day=(datetime(2024,9,1)+timedelta(days=(w-1)*7)).date().isoformat()
            self.schedule.append(dict(game_id=gid,season=2024,week=w,game_type='REG',gameday=day,gametime='13:00',away_team='NE',home_team='BUF',away_score=20+w,home_score=25))
            for t,o in [('NE','BUF'),('BUF','NE')]:
                self.teams.append(dict(game_id=gid,season=2024,week=w,season_type='REG',team=t,opponent_team=o,attempts=30,completions=20,carries=20,passing_yards=230,rushing_yards=90,passing_epa=w,rushing_epa=-1,sacks_suffered=2))
                self.players.append(dict(self.teams[-1],player_id='00-0000001' if t=='NE' else '00-0000002',position='WR',player_display_name='Same Name',targets=8,receptions=5,receiving_yards=80))
        self.load('schedule',self.schedule);self.load('team',self.teams);self.load('player',self.players)
    def load(self,kind,rows,captured=CAP):
        p=self.root/(kind+'.csv')
        with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        return ingest(self.db,p,kind,season=2024,captured_at=captured,url='https://example.test/fixture')
    def test_idempotency(self):
        self.assertTrue(self.load('player',self.players)['unchanged'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM observations WHERE kind='player'").fetchone()[0],16)
    def test_duplicate_rolls_back_refresh(self):
        before=self.db.execute('SELECT count(*) FROM observations').fetchone()[0]
        with self.assertRaises(ValueError):self.load('player',self.players+[self.players[0]])
        self.assertEqual(self.db.execute('SELECT count(*) FROM observations').fetchone()[0],before)
    def test_nonfinite_and_impossible_counts(self):
        for key,value in [('passing_epa','inf'),('targets',-1),('receptions',999)]:
            rows=copy.deepcopy(self.players);rows[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.load('player',rows)
    def test_wrong_opponent_and_missing_id_rejected(self):
        for key,value in [('opponent_team','DAL'),('player_id','Same Name')]:
            rows=copy.deepcopy(self.players);rows[0][key]=value
            with self.assertRaises(ValueError):self.load('player',rows)
    def test_missing_column_rejected(self):
        rows=copy.deepcopy(self.players)
        for r in rows:r.pop('targets')
        with self.assertRaises(ValueError):self.load('player',rows)
    def test_same_name_distinct_ids(self):
        f=build(self.db,'NE','BUF','2024-10-25T00:00:00+00:00')
        self.assertNotEqual(f['teams'][0]['players'][0]['player_id'],f['teams'][1]['players'][0]['player_id'])
    def test_target_and_future_mutations_do_not_change_features(self):
        cutoff='2024-09-22T17:00:00+00:00';before=build(self.db,'NE','BUF',cutoff)
        self.db.execute("UPDATE observations SET payload='{}' WHERE gid>='2024_04_NE_BUF'")
        self.assertEqual(before,build(self.db,'NE','BUF',cutoff))
    def test_late_capture_unavailable_in_strict_mode(self):
        self.load('player',self.players+[dict(self.players[0],player_id='00-9999999')],captured='2025-01-01T00:00:00+00:00')
        strict=build(self.db,'NE','BUF','2024-10-25T00:00:00+00:00')
        self.assertEqual([p['player_id'] for p in strict['teams'][0]['players']],['00-0000001'])
        retro=build(self.db,'NE','BUF','2024-10-25T00:00:00+00:00',mode='retrospective')
        self.assertTrue(retro['teams'][0]['players']);self.assertFalse(retro['historical_publication_verified'])
    def test_game_delay_and_timezone(self):
        self.assertFalse(list(history(self.db,'2024-09-02T00:00:00+00:00')))
        with self.assertRaises(ValueError):list(history(self.db,'2024-10-01'))
        self.assertTrue(list(history(self.db,'2024-09-05T00:00:00+00:00')))
    def test_missing_metrics_have_exposures_not_fake_zero(self):
        self.assertEqual(rate([{'values':{'x':None,'n':3}}],'x','n')['exposure'],0)
        f=build(self.db,'NE','BUF','2024-10-25T00:00:00+00:00')
        self.assertEqual(f['teams'][0]['neutral_pass_epa']['exposure'],0)
        self.assertIn('receiver_X_Z_slot_alignment',f['gaps'])
    def test_transfer_uses_latest_known_team(self):
        self.db.execute("UPDATE observations SET pid='00-0000001' WHERE kind='player' AND gid='2024_08_NE_BUF' AND team='BUF'")
        self.db.execute("DELETE FROM observations WHERE kind='player' AND gid='2024_08_NE_BUF' AND team='NE'")
        f=build(self.db,'NE','BUF','2024-10-25T00:00:00+00:00')
        self.assertNotIn('00-0000001',[p['player_id'] for p in f['teams'][0]['players']])
    def test_incremental_correction_keeps_schedule_links(self):
        self.schedule[0]['away_score']=17;self.load('schedule',self.schedule)
        self.assertEqual(self.db.execute('SELECT count(*) FROM observations').fetchone()[0],32)
    def test_retention_guard_and_disk_cap(self):
        self.assertLessEqual(self.db.execute('PRAGMA max_page_count').fetchone()[0]*4096,LIMIT)
        with self.assertRaises(ValueError):maintain(self.db,keep_seasons=1)
        self.assertEqual(maintain(self.db)['removed_research_seasons'],[])
    def test_late_correction_excludes_only_changed_rows(self):
        rows=copy.deepcopy(self.players);rows[0]['receiving_yards']=99
        self.load('player',rows,captured='2025-01-01T00:00:00+00:00')
        old=self.db.execute("SELECT available FROM observations WHERE kind='player' AND gid='2024_02_NE_BUF' AND team='NE'").fetchone()[0]
        changed=self.db.execute("SELECT available FROM observations WHERE kind='player' AND gid='2024_01_NE_BUF' AND team='NE'").fetchone()[0]
        self.assertEqual(old,CAP);self.assertEqual(changed,'2025-01-01T00:00:00+00:00')
        admitted=list(history(self.db,'2024-10-25T00:00:00+00:00'))
        self.assertFalse(any(r['kind']=='player' and r['gid']=='2024_01_NE_BUF' and r['team']=='NE' for r in admitted))

    def test_retention_deletes_only_own_oldest_seasons(self):
        for year in (2020,2021,2022):
            self.db.execute('INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?)',(str(year),year,1,f'{year}-09-01T00:00:00+00:00',f'{year}-09-02T00:00:00+00:00',CAP,'NE','BUF',0,0))
        self.db.commit()
        self.assertEqual(maintain(self.db,keep_seasons=3)['removed_research_seasons'],[2020])
        self.assertEqual(self.db.execute('SELECT count(*) FROM observations').fetchone()[0],32)

    def test_ridge_warmup_and_deterministic_evaluation(self):
        m=Ridge(2);self.assertEqual(m.predict([1,2]),0)
        for i in range(40):m.update([1,2],3)
        self.assertGreater(m.predict([1,2]),0)
        a=evaluate(self.db,train_season=2023,mode='observed');b=evaluate(self.db,train_season=2023,mode='observed')
        self.assertEqual(a,b);self.assertIn('2024',a['seasons'])



class PlayByPlayTests(unittest.TestCase):
    def test_charting_availability_and_duplicate_keys(self):
        import polars as pl
        from .pbp import ingest_pbp,ingest_charting
        fixture=EngineTests();fixture.setUp()
        try:
            rows=[]
            for play in (1,2,3):
                rows.append(dict(game_id='2024_01_NE_BUF',season=2024,week=1,posteam='NE',defteam='BUF',
                    play_type='pass',qb_dropback=1.,epa=float(play),wp=.5,qtr=2.,sack=0.,qb_hit=float(play==1),
                    passer_player_id='00-0000003',cpoe=1.,rush_attempt=0.,play_id=float(play)))
            p=fixture.root/'pbp.parquet';pl.DataFrame(rows).write_parquet(p)
            ingest_pbp(fixture.db,p,season=2024,captured_at=CAP,url='fixture')
            chart=pl.DataFrame(dict(nflverse_game_id=['2024_01_NE_BUF']*2,play_id=[1,2],number_of_pass_rushers=[5,4],was_pressure=[True,False],defense_man_zone_type=['MAN_COVERAGE','ZONE_COVERAGE']))
            cp=fixture.root/'chart.parquet';chart.write_parquet(cp)
            ingest_charting(fixture.db,cp,p,season=2024,captured_at='2025-02-01T00:00:00+00:00',url='fixture')
            f=build(fixture.db,'NE','BUF','2024-09-08T17:00:00+00:00')
            self.assertEqual(f['teams'][0]['verified_pressure_response']['exposure'],0)
            retro=build(fixture.db,'NE','BUF','2024-09-08T17:00:00+00:00',mode='retrospective')
            self.assertEqual(retro['teams'][0]['verified_pressure_response']['exposure'],1)
            self.assertEqual(retro['teams'][0]['opponent_five_plus_rusher_rate']['exposure'],2)
            self.assertTrue(ingest_charting(fixture.db,cp,p,season=2024,captured_at=CAP,url='fixture')['unchanged'])
            pl.concat([chart,chart.head(1)]).write_parquet(cp)
            with self.assertRaises(ValueError):ingest_charting(fixture.db,cp,p,season=2024,captured_at=CAP,url='fixture')
            pl.DataFrame(rows+[rows[0]]).write_parquet(p)
            with self.assertRaises(ValueError):ingest_pbp(fixture.db,p,season=2024,captured_at=CAP,url='fixture')
            bad=copy.deepcopy(rows);bad[0]['epa']=float('inf');pl.DataFrame(bad).write_parquet(p)
            with self.assertRaises(ValueError):ingest_pbp(fixture.db,p,season=2024,captured_at=CAP,url='fixture')
        finally:fixture.doCleanups()

if __name__=='__main__':unittest.main()
