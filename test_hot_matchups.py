"""Run: python -m unittest -v test_hot_matchups.py (no web or database)."""
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from hot_matchups import (qualifies_upcoming, upcoming_for_trend, matches_for_score,
                          is_fireworthy, is_standout_primetime_dog, scorecard_trends,
                          hot_trend_id, current_season_research_params,
                          current_season_evidence)

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=ZoneInfo('America/New_York'))
WEEK = (2026, 7)


def game(**overrides):
    data = dict(game_id='2026_07_GB_DET', season='2026', week='7',
                game_type='REG', gameday='2026-10-25', gametime='20:20',
                away_team='GB', home_team='DET',
                spread_line='3', total_line='45.5', location='home')
    data.update(overrides)
    return data


def trend(category='team', kind='su', **kwargs):
    params={'research_team':'GB'} if category=='team' else {'primetime':'yes'}
    if category=='qb':params={'qb_name':'Quarterback A'}
    evidence=[dict(game_id=f'2026_0{i}_GB_DET', result='Win', date='2026-10-18') for i in range(1,6)]
    data=dict(category=category, kind=kind, params=params, season=2026,
              evidence=evidence, title='Test', outcome='Win', streak=5, wins=5)
    data.update(kwargs)
    return data


class HotMatchupTests(unittest.TestCase):
    def yes(self, g=None, t=None):
        self.assertTrue(qualifies_upcoming(g or game(), t or trend(), now=NOW, active_week=WEEK))

    def no(self, g=None, t=None):
        self.assertFalse(qualifies_upcoming(g or game(), t or trend(), now=NOW, active_week=WEEK))

    def test_team_present(self): self.yes()
    def test_other_team(self): self.no(t=trend(params={'research_team':'NE'}))
    def test_home_team(self): self.yes(t=trend(params={'research_team':'DET'}))
    def test_team_total_has_saved_total(self): self.no(g=game(total_line=''), t=trend(kind='total'))
    def test_team_ats_requires_saved_spread(self): self.no(g=game(spread_line=''), t=trend(kind='ats'))
    def test_team_ats_valid(self): self.yes(t=trend(kind='ats'))
    def test_team_su_independent_of_lines(self): self.yes(g=game(spread_line='',total_line=''))
    def test_unknown_market_is_not_zero(self): self.no(g=game(spread_line='nan'), t=trend(kind='ats'))
    def test_not_reg(self): self.no(g=game(game_type='SB'))
    def test_no_kickoff(self): self.no(g=game(gametime=''))
    def test_already_kicked_off(self): self.no(g=game(gameday='2026-10-21',gametime='13:00'))
    def test_previous_week(self): self.no(g=game(week='6'))
    def test_future_week(self): self.no(g=game(week='8'))
    def test_wrong_season(self): self.no(g=game(season='2025'))
    def test_wrong_trend_season(self): self.no(t=trend(season=2025))
    def test_situation_home_underdog(self):
        t=trend('situational','ats',params={'primetime':'yes','research_role':'underdog','research_location':'home'})
        self.yes(g=game(spread_line='-3'),t=t)
        self.no(g=game(spread_line='3'),t=t)
        self.no(g=game(spread_line='-3',gametime='13:00'),t=t)
        self.no(g=game(spread_line='-3',location='neutral'),t=t)
        self.no(g=game(spread_line='0'),t=t)
    def test_situation_away_underdog(self):
        t=trend('situational','ats',params={'primetime':'yes','research_role':'underdog','research_location':'away'})
        self.yes(g=game(spread_line='3'),t=t)
        self.no(g=game(spread_line='-3'),t=t)
    def test_situation_favorite(self):
        t=trend('situational','ats',params={'primetime':'yes','research_role':'favorite','research_location':'home'})
        self.yes(g=game(spread_line='3'),t=t)
        self.no(g=game(spread_line='-3'),t=t)
    def test_situation_total_nonprimetime(self):
        t=trend('situational','total',params={'primetime':'no'})
        self.yes(g=game(gametime='13:00'),t=t)
        self.no(g=game(gametime='20:00'),t=t)
        self.no(g=game(gametime='13:00',total_line=''),t=t)
    def test_invalid_situation_rejected(self):
        self.no(t=trend('situational','ats',params={'research_role':'all','primetime':'yes'}))
    def test_weekupcoming_sorted(self):
        games=[game(game_id='later',gameday='2026-10-26'), game(game_id='earlier',gameday='2026-10-22'),
               game(game_id='past',gameday='2026-10-15')]
        self.assertEqual([g['game_id'] for g in upcoming_for_trend(games,trend(),now=NOW,active_week=WEEK)], ['earlier','later'])
    def test_historical_requires_exact_evidence(self):
        a=trend(evidence=[{'game_id':'2026_07_GB_DET','result':'Win'}] +
                [dict(game_id=f'2026_0{i}_GB_DET',result='Win') for i in range(1,5)])
        b=trend(evidence=[{'game_id':'2026_06_GB_DET','result':'Win'}] +
                [dict(game_id=f'2026_0{i}_GB_DET',result='Win') for i in range(1,5)])
        self.assertEqual(matches_for_score(game(),[a,b],state='post'),[a])
    def test_future_not_classified_live(self):
        self.assertEqual(matches_for_score(game(),[trend()],state='in',now=NOW,active_week=WEEK),[])
    def test_future_match(self):
        self.assertEqual(len(matches_for_score(game(),[trend()],state='pre',now=NOW,active_week=WEEK)),1)
    def test_qb_requires_source_and_confirmation(self):
        t=trend('qb')
        stub=types.ModuleType('trend_finder_2')
        stub.canonical_name=lambda value:(str(value).lower().strip() if value else '')
        with patch.dict(sys.modules, {'trend_finder_2':stub}):
            self.no(g=game(away_qb_name='Quarterback A'),t=t)
            self.no(g=game(away_qb_name='Quarterback A',away_qb_status='expected',away_qb_source='official'),t=t)
            self.no(g=game(away_qb_name='Quarterback A',away_qb_status='confirmed'),t=t)
            self.yes(g=game(away_qb_name='Quarterback A',away_qb_status='confirmed',away_qb_source='official'),t=t)
            self.no(g=game(away_qb_name='Other QB',away_qb_status='confirmed',away_qb_source='official'),t=t)

    def test_fire_requires_current_season_sample(self):
        t=trend()
        self.assertTrue(is_fireworthy(t))
        mixed = trend(evidence=[dict(game_id=f'2025_0{i}_GB_DET', result='Win') for i in range(1,5)] +
                      [dict(game_id='2026_06_GB_DET',result='Win')])
        self.assertFalse(is_fireworthy(mixed))

    def test_fire_rejects_generic_league_wide_totals(self):
        broad=trend('situational','total',params={'primetime':'no'})
        self.assertFalse(is_fireworthy(broad))
        self.assertEqual(upcoming_for_trend([game(gametime='13:00')], broad,now=NOW,active_week=WEEK),[])
        self.assertEqual(matches_for_score(game(),[broad],state='pre',now=NOW,active_week=WEEK),[])

    def test_fire_rejects_wide_situational_role(self):
        broad=trend('situational','ats',params={'primetime':'yes','research_role':'underdog','research_location':''})
        self.assertFalse(is_fireworthy(broad))
        specific=trend('situational','ats',params={'primetime':'yes','research_role':'underdog','research_location':'home'})
        self.assertTrue(is_fireworthy(specific))

    def test_fire_requires_four_this_season_favorable_results(self):
        t=trend(evidence=[dict(game_id=f'2026_0{i}_GB_DET',result='Loss') for i in range(1,3)] +
                         [dict(game_id=f'2026_0{i}_GB_DET',result='Win') for i in range(3,6)])
        self.assertFalse(is_fireworthy(t))

    def test_12_straight_primetime_underdog_covers_qualifies_ne_chi(self):
        streak = trend('situational', 'ats',
            params={'primetime':'yes', 'research_role':'underdog', 'research_location':''},
            title='Primetime underdogs — ATS', outcome='Cover', streak=12,
            evidence=[{'game_id':f'2026_{i:02}_A_B','result':'Cover'} for i in range(1,13)])
        patriots = game(game_id='2026_07_NE_CHI', away_team='NE', home_team='CHI',
                        gameday='2026-10-22', gametime='20:15', spread_line='3')
        self.assertTrue(is_standout_primetime_dog(streak))
        self.assertTrue(is_fireworthy(streak))
        self.assertEqual(matches_for_score(patriots, [streak], state='pre',
                         now=NOW, active_week=WEEK), [streak])
        self.assertEqual(upcoming_for_trend([patriots], streak, now=NOW, active_week=WEEK),
                         [patriots])
        # In a location-free underdog trend either side may be the dog,
        # but missing lines or non-primetime games cannot qualify.
        self.assertEqual(matches_for_score(game(away_team='NE',home_team='CHI',
                         spread_line=''), [streak], state='pre',now=NOW,active_week=WEEK),[])
        self.assertEqual(matches_for_score(game(away_team='NE',home_team='CHI',
                         gametime='13:00'), [streak], state='pre',now=NOW,active_week=WEEK),[])

    def test_long_streak_not_in_featured_top_eight_still_shows(self):
        selected = [trend(title='Featured GB',subject='team:GB')]
        special = trend('situational', 'ats',
            params={'primetime':'yes', 'research_role':'underdog', 'research_location':''},
            title='Primetime underdogs — ATS', subject='situation:underdog:yes:',
            outcome='Cover', streak=12,
            evidence=[{'game_id':f'2026_{i:02}_A_B','result':'Cover'} for i in range(1,13)])
        generic=trend('situational','ats',
            params={'primetime':'no', 'research_role':'underdog', 'research_location':''},
            title='Generic league wide', subject='situation:underdog:no:',
            outcome='Cover',streak=12,
            evidence=[{'game_id':f'2026_{i:02}_A_B','result':'Cover'} for i in range(1,13)])
        self.assertEqual(scorecard_trends(selected,[selected[0],special,generic]),
                         [selected[0],special])
        self.assertEqual(scorecard_trends([special],[special]),[special])

    def test_no_broad_fire_for_short_primetime_streak(self):
        short=trend('situational','ats', params={'primetime':'yes',
                    'research_role':'underdog','research_location':''},
                    outcome='Cover', streak=9,
                    evidence=[{'game_id':f'2026_{i:02}_A_B','result':'Cover'} for i in range(1,10)])
        self.assertFalse(is_standout_primetime_dog(short))
        self.assertFalse(is_fireworthy(short))
        self.assertFalse(is_standout_primetime_dog(dict(short, outcome='Loss',streak=12)))

    def test_twelve_streak_from_prior_season_not_fireworthy(self):
        old=trend('situational','ats', params={'primetime':'yes',
                    'research_role':'underdog','research_location':''},
                    outcome='Cover', streak=12,
                    evidence=[{'game_id':f'2025_{i:02}_A_B','result':'Cover'}
                              for i in range(1,13)])
        self.assertTrue(is_standout_primetime_dog(old))
        self.assertFalse(is_fireworthy(old))

    def test_fire_anchor_stable_unique_and_season_research(self):
        t=trend(params={'research_team':'CLE','research_view':'general', 'run':'analyze'})
        self.assertEqual(hot_trend_id(t),hot_trend_id(dict(t)))
        self.assertNotEqual(hot_trend_id(t),hot_trend_id(trend(kind='ats')))
        params=current_season_research_params(t)
        self.assertEqual(params['season'],2026)
        self.assertNotIn('season',t['params'])
        self.assertEqual(len(current_season_evidence(t)),5)

    def test_full_selection_does_not_mark_unrelated_games(self):
        t=trend(params={'research_team':'NE'})
        self.assertEqual(matches_for_score(game(),[t],state='pre',now=NOW,active_week=WEEK),[])

if __name__=='__main__':unittest.main()
