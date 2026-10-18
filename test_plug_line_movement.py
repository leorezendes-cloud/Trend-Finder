import copy
import unittest
from datetime import datetime,timezone
from plug_line_movement import compare_line
def fixture():
    return {'game':{'game_id':'2099_01_HOU_JAX','away_team':'HOU','home_team':'JAX','kickoff_utc':'2099-09-10T17:00:00+00:00'},'cutoff_utc':'2099-09-10T12:00:00+00:00','scores':{'HOU':24,'JAX':21},'spread':{'side':'HOU'},'quotes':{'Spread':{'game_id':'2099_01_HOU_JAX','side_a':'HOU','side_b':'JAX','line_a':3,'line_b':-3,'captured_at_utc':'2099-09-10T12:00:00+00:00'}}}

class MovementTests(unittest.TestCase):
    def setUp(self):
        self.s=fixture();self.s['quotes']['Spread']['sportsbook']='Fixture';self.now=datetime(2099,9,10,13,tzinfo=timezone.utc)
        self.row=dict(game_id=self.s['game']['game_id'],kickoff_utc=self.s['game']['kickoff_utc'],captured_at_utc='2099-09-10T12:30:00+00:00',away_team='HOU',home_team='JAX',sportsbook='Fixture',source_url='https://example.test/line',market='Spread',side_a='HOU',side_b='JAX',line_a='-4',line_b='4',odds_a='-110',odds_b='-110',handle_a='50',handle_b='50',bets_a='50',bets_b='50')
    def check(self,rows):return compare_line(self.s,'.',self.now,rows=rows)
    def test_flip_edge_and_immutability(self):
        before=copy.deepcopy(self.s);m=self.check([self.row]);self.assertEqual(m['original_edge'],6);self.assertEqual(m['latest_edge'],-1);self.assertTrue(m['unsupported']);self.assertTrue(m['material']);self.assertEqual(before,self.s)
    def test_same_book_only_and_latest(self):
        wrong={**self.row,'sportsbook':'Other','line_a':'8','line_b':'-8','captured_at_utc':'2099-09-10T12:45:00+00:00'}
        self.assertEqual(self.check([self.row,wrong])['latest_line'],-4);self.assertIsNone(self.check([wrong]))
    def test_wrong_game_future_postkickoff_and_older_excluded(self):
        for change in ({'game_id':'other'},{'captured_at_utc':'2099-09-10T14:00:00+00:00'},{'captured_at_utc':'2099-09-10T17:01:00+00:00'},{'captured_at_utc':'2099-09-10T11:00:00+00:00'}):self.assertIsNone(self.check([{**self.row,**change}]))
    def test_push_and_unchanged(self):
        m=self.check([{**self.row,'line_a':'-3','line_b':'3'}]);self.assertEqual(m['latest_edge'],0);self.assertTrue(m['unsupported'])
        m=self.check([{**self.row,'line_a':'3','line_b':'-3'}]);self.assertEqual(m['movement'],0);self.assertFalse(m['material']);self.assertFalse(m['unsupported'])
    def test_minor_move_still_supported(self):
        m=self.check([{**self.row,'line_a':'2.5','line_b':'-2.5'}]);self.assertEqual(m['movement'],-.5);self.assertFalse(m['material']);self.assertFalse(m['unsupported'])
    def test_missing_metadata_does_not_guess_book(self):
        del self.s['quotes']['Spread']['sportsbook'];self.assertIsNone(self.check([self.row]))
