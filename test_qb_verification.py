import copy,json,tempfile,unittest,csv
from pathlib import Path
from unittest.mock import Mock
from qb_verification import verified_starters,refresh_qbs
from research_qbs import research_rows
from general_research import result_streak,research_games
from app import app


def fixture():
    game=dict(game_id='2026_06_SEA_DEN',season='2026',gameday='2026-10-15',gametime='20:15',
              away_team='SEA',home_team='DEN',away_score='14',home_score='17',
              away_qb_name='',home_qb_name='Wrong QB',espn='123')
    contest=dict(date='2026-10-16T00:15:00Z',status={'type':{'completed':True}},
                 competitors=[{'homeAway':s,'team':{'abbreviation':game[s+'_team']},'score':game[s+'_score']} for s in ('home','away')])
    players=[]
    for code,name in [('SEA','Sam Darnold'),('DEN','Bo Nix')]:
        players.append({'team':{'abbreviation':code},'statistics':[{'name':'passing','athletes':[
            {'starter':True,'athlete':{'displayName':name},'stats':['1','2']},
            {'starter':False,'athlete':{'displayName':'Backup'},'stats':['40','50']}]}]})
    return game,{'header':{'competitions':[contest]},'boxscore':{'players':players}}


class VerificationTests(unittest.TestCase):
    def test_explicit_starter_not_most_attempts(self):
        game,payload=fixture()
        self.assertEqual(verified_starters(payload,game),{'away':'Sam Darnold','home':'Bo Nix'})

    def test_missing_ambiguous_and_nonfinal_fail_closed(self):
        game,payload=fixture()
        changes=[]
        missing=copy.deepcopy(payload);del missing['boxscore']['players'][0]['statistics'][0]['athletes'][0]['starter'];changes.append(missing)
        ambiguous=copy.deepcopy(payload);ambiguous['boxscore']['players'][0]['statistics'][0]['athletes'][1]['starter']=True;changes.append(ambiguous)
        nonfinal=copy.deepcopy(payload);nonfinal['header']['competitions'][0]['status']['type']['completed']=False;changes.append(nonfinal)
        wrongscore=copy.deepcopy(payload);wrongscore['header']['competitions'][0]['competitors'][0]['score']='99';changes.append(wrongscore)
        for item in changes:
            with self.assertRaises(ValueError):verified_starters(item,game)

    def test_refresh_saves_verified_research_overlay_and_flags_failed_checks(self):
        game,payload=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'nfl_games.csv'
            with path.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(game));writer.writeheader();writer.writerow(game)
            fetch=Mock(return_value=payload)
            refresh_qbs(root,2026,fetch=fetch)
            corrected=research_rows([game],path)[0]
            self.assertEqual(corrected['away_qb_name'],'Sam Darnold')
            self.assertEqual(corrected['home_qb_name'],'Bo Nix')
            self.assertEqual(game['home_qb_name'],'Wrong QB')
            refresh_qbs(root,2026,fetch=fetch)
            self.assertEqual(fetch.call_count,1)
            (root/'data/research_qbs/verified.json').unlink()
            with self.assertRaises(ValueError):refresh_qbs(root,2026,fetch=Mock(side_effect=OSError('Feed unavailable')))
            audit=json.loads((root/'data/research_qbs/verified.json').read_text())
            self.assertEqual(audit['games'],{})
            self.assertEqual(audit['issues'][0]['game_id'],game['game_id'])

    def test_streak_stops_at_loss_push_or_unavailable(self):
        self.assertEqual(result_streak(['Cover','Cover','Loss']),'2 straight covers')
        self.assertEqual(result_streak(['Loss','Loss','Cover']),'2 straight losses')
        self.assertEqual(result_streak(['Push','Cover']),'1 straight push')
        self.assertEqual(result_streak([None,'Cover']),'Latest result unavailable')

    def test_manual_underdog_cards_hide_other_roles_and_show_streak(self):
        html=app.test_client().get('/trend-finder?research_view=general&run=analyze&season=2026&research_role=underdog&primetime=yes').text
        self.assertIn('Dogs ATS',html)
        self.assertIn('class="current-streak"',html)
        self.assertNotIn('Favorites ATS',html)
        self.assertNotIn('Home team ATS',html)
        self.assertIn('<th>Favorite</th>',html)
        self.assertIn('<th>Underdog ATS</th>',html)

if __name__=='__main__':unittest.main()
