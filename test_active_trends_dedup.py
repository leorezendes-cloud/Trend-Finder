import unittest
from active_trends import _feature


def trend(subject, scope, kind, outcome, games, *, role=None, location=None, prime='yes', streak=5):
    return dict(subject=subject, scope=scope, kind=kind, outcome=outcome,
                category='situational' if scope == 'situational' else scope,
                streak=streak, wins=7, latest='2026-11-22', pushes=0,
                title=subject, evidence=[dict(game_id=g, result=outcome) for g in games],
                params=dict(research_role=role, research_location=location, primetime=prime))


class HomepageTrendDedupTests(unittest.TestCase):
    def test_qb_and_team_identical_su_streak_choose_team(self):
        games = ['g'+str(i) for i in range(7)]
        qb = trend('qb:Example', 'qb', 'su', 'Win', games)
        team = trend('team:ABC', 'team', 'su', 'Win', games)
        result = _feature([qb, team])
        self.assertEqual([x['subject'] for x in result], ['team:ABC'])

    def test_team_and_qb_different_length_same_recent_run(self):
        games = ['g'+str(i) for i in range(9)]
        team = trend('team:DEN', 'team', 'su', 'Win', games, streak=9)
        qb = trend('qb:Bo Nix', 'qb', 'su', 'Win', games[:6], streak=6)
        self.assertEqual([x['subject'] for x in _feature([team, qb])], ['team:DEN'])

    def test_different_recent_games_remain_separate(self):
        team = trend('team:DEN', 'team', 'su', 'Win',
                     ['g'+str(i) for i in range(7)], streak=7)
        qb = trend('qb:Other', 'qb', 'su', 'Win',
                   ['x'] + ['g'+str(i) for i in range(6)], streak=7)
        self.assertEqual(len(_feature([team, qb])), 2)

    def test_opposing_situational_ats_stories_choose_favorite(self):
        games = ['g'+str(i) for i in range(7)]
        fav = trend('favorite', 'situational', 'ats', 'Cover', games, role='favorite', location='home')
        dog = trend('underdog', 'situational', 'ats', 'Loss', games, role='underdog', location='away')
        result = _feature([dog, fav])
        self.assertEqual([x['subject'] for x in result], ['favorite'])

    def test_distinct_evidence_is_not_suppressed(self):
        a = trend('team:A', 'team', 'su', 'Win', ['a'+str(i) for i in range(7)])
        b = trend('qb:B', 'qb', 'su', 'Win', ['b'+str(i) for i in range(7)])
        self.assertEqual(len(_feature([a, b])), 2)


if __name__ == '__main__':
    unittest.main()
