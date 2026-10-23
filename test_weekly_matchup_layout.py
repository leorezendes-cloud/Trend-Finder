"""Underdog history stays distinct from the current game's ATS result."""
import unittest
from html.parser import HTMLParser
from weekly_results import underdog_records


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__();self.in_table=False;self.in_header=False;self.in_cell=False;self.headers=[];self.rows=[];self.cells=0
    def handle_starttag(self,tag,attrs):
        if tag=='table' and dict(attrs).get('class')=='weekly-results-table':self.in_table=True
        if not self.in_table:return
        if tag=='tr':self.cells=0
        if tag=='th':self.in_header=True;self.headers.append('')
        if tag=='td':self.cells+=1
    def handle_data(self,data):
        if self.in_header:self.headers[-1]+=data
    def handle_endtag(self,tag):
        if tag=='th':self.in_header=False
        if tag=='tr' and self.in_table and self.cells:self.rows.append(self.cells)
        if tag=='table':self.in_table=False


class WeeklyMatchupTests(unittest.TestCase):
    def test_underdog_history_is_season_and_pregame_scoped(self):
        def game(week,away,home,line,a,h,**extra):
            return dict(game_type='REG',season='2026',week=str(week),away_team=away,home_team=home,spread_line=str(line),away_score=str(a),home_score=str(h),**extra)
        rows=[game(1,'A','B',3,20,21),game(2,'B','A',-2,20,15),game(3,'A','B',3,17,20),game(4,'A','B',-3,30,10),game(6,'A','B',3,30,10),game(5,'A','B',0,30,10),game(5,'A','B','',30,10),game(5,'A','B',3,'','')]
        rows.append(dict(rows[0],season='2025'))
        rows.append(dict(rows[0],game_type='WC'))
        records=underdog_records(rows,2026,6)
        self.assertEqual(records['A'],{'Cover':1,'Loss':1,'Push':1})

    def test_desktop_headers_and_cells_match_requested_order(self):
        from app import app
        expected=['Matchup','Scores','Underdog','ATS as Dog','Result',"Plug's Pick",'Plug Total','Plug Result','Details']
        for week in (5,6):
            with self.subTest(week=week):
                response=app.test_client().get(f'/sunday-results?week={week}')
                self.assertEqual(response.status_code,200)
                parser=TableParser();parser.feed(response.text)
                self.assertEqual(parser.headers,expected)
                self.assertTrue(parser.rows)
                self.assertTrue(all(count==len(expected) for count in parser.rows))
                self.assertIn('entering Week',response.text)
                self.assertNotIn('Score / status',response.text)

    def test_market_redirects_to_the_plug(self):
        from app import app
        response=app.test_client().get('/market')
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/the-plug')
