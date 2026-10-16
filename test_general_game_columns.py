import unittest
from pathlib import Path
from html.parser import HTMLParser
from flask import Flask,render_template

class Table(HTMLParser):
    def __init__(self):super().__init__();self.headers=[];self.rows=[];self.cell=None;self.text=''
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.rows.append([])
        if tag in ('td','th'):self.cell=tag;self.text=''
    def handle_data(self,data):
        if self.cell:self.text+=data
    def handle_endtag(self,tag):
        if tag==self.cell:
            self.rows[-1].append(self.text.strip())
            if tag=='th':self.headers.append(self.text.strip())
            self.cell=None

class FixedDogColumnsTests(unittest.TestCase):
    def test_dog_columns_stay_correct_for_every_search_context(self):
        app=Flask(__name__,template_folder=str(Path(__file__).parent/'templates'))
        app.add_url_rule('/matchup/<game_id>',endpoint='fans.matchup',view_func=lambda game_id:'')
        base=dict(game_id='sea_den',gameday='2026-10-15',gametime='20:15',away_team='SEA',home_team='DEN',away_score=14,home_score=17,spread=-2.5,total=40.5,total_result='Under',away_ats='Loss',home_ats='Cover',favorite='SEA',underdog='DEN',dog_side='home',favorite_side='away',selected_side=None,focus_side=None)
        games=[base,dict(base,game_id='away_dog',spread=3,favorite='DEN',underdog='SEA',dog_side='away',favorite_side='home',away_ats='Push',home_ats='Push'),dict(base,game_id='pickem',spread=0,favorite=None,underdog=None,dog_side=None,favorite_side=None),dict(base,game_id='missing',spread=None,favorite=None,underdog=None,dog_side=None,favorite_side=None)]
        for metric in ('','Underdogs ATS','Favorites ATS','Away teams ATS','Under'):
            with self.subTest(metric=metric),app.test_request_context('/'):
                html=render_template('_general_games.html',games=games,total=4,preview=True,evidence_metric=metric)
                table=Table();table.feed(html)
                self.assertEqual(table.headers[4:7],['Favorite','Underdog','Underdog ATS'])
                self.assertEqual(table.rows[1][4:7],['SEA','DEN','Cover'])
                self.assertEqual(table.rows[2][4:7],['DEN','SEA','Push'])
                self.assertEqual(table.rows[3][4:7],['Pick’em','Pick’em','No underdog'])
                self.assertEqual(table.rows[4][4:7],['Unavailable','Unavailable','Unavailable'])

if __name__=='__main__':unittest.main()
