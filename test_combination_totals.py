import unittest
from general_research import find_combinations, group_overlapping_trends

class CombinationTotalsTests(unittest.TestCase):
    def test_totals_survive_stronger_ats_for_same_conditions(self):
        for outcome,total in [('Over','43'),('Under','45')]:
            rows=[dict(game_id=str(i),season='2025',gameday='2025-11-09',gametime='20:20',game_type='REG',away_team='BUF',home_team='NYJ',away_score='24' if i<10 else ('20' if outcome=='Over' else '30'),home_score='20',spread_line='3',total_line=total) for i in range(12)]
            rows.append(dict(rows[0],game_id='push',away_score='21.5' if outcome=='Over' else '22.5',home_score='21.5' if outcome=='Over' else '22.5'))
            rows.append(dict(rows[0],game_id='missing',total_line=''))
            trends=find_combinations(rows)
            self.assertIn(outcome,{t['label'] for t in trends})
            trend=next(t for t in trends if t['label']==outcome)
            self.assertEqual((trend['wins'],trend['losses'],trend['pushes']),(10,2,1))
            self.assertAlmostEqual(trend['rate'],100*10/12)
            self.assertTrue(any(t['label'].endswith(' ATS') for t in trends))

    def test_result_limit_keeps_all_available_markets(self):
        def trend(label,i,score):return dict(label=label,conditions={'roof':str(i)},membership=(i,),recent_games=12,sample=12,score=score)
        rows=[trend('Home teams ATS',i,.99) for i in range(10)]
        rows.extend([trend('Over',20,.7),trend('Under',21,.6)])
        result=group_overlapping_trends(rows,limit=3)
        self.assertEqual({t['label'] for t in result},{'Home teams ATS','Over','Under'})

if __name__=='__main__':unittest.main()
