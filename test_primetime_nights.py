import unittest,re
from html import unescape
from urllib.parse import urlsplit,parse_qs
from werkzeug.datastructures import MultiDict
from primetime_nights import normalize_nights,matches_nights
from general_research import research_games
from saved_trends import manual_trend_title
from app import app

class PrimetimeNightTests(unittest.TestCase):
 def test_combined_sunday_monday_totals_exclude_daytime_and_thursday(self):
  def game(ident,day,clock,home,away):return dict(game_id=ident,season='2025',gameday=day,gametime=clock,game_type='REG',away_team='BUF',home_team='NYJ',away_score=str(away),home_score=str(home),spread_line='3',total_line='45')
  rows=[game('sun','2025-11-09','20:20',30,20),game('mon','2025-11-10','20:15',20,17),game('thu','2025-11-06','20:15',30,20),game('day','2025-11-09','13:00',30,20)]
  report=research_games(rows,primetime_nights=('sun','mon'))
  self.assertEqual({g['game_id'] for g in report['matches']},{'sun','mon'})
  self.assertEqual(report['totals']['over'],1);self.assertEqual(report['totals']['under'],1)
  self.assertEqual(research_games(rows,primetime_nights=('sun',))['totals']['over'],1)
  self.assertEqual(research_games(rows,primetime_nights=('mon',))['totals']['under'],1)
 def test_normalization_and_night_boundaries(self):
  form=normalize_nights(MultiDict([('primetime_nights','sun'),('primetime_nights','mon')]))
  self.assertEqual(form['primetime_nights'],'sun,mon');self.assertEqual(form['primetime'],'yes')
  self.assertTrue(matches_nights({'gameday':'2025-11-09','gametime':'19:00'},('sun',)))
  self.assertFalse(matches_nights({'gameday':'2025-11-09','gametime':'18:59'},('sun',)))
  with self.assertRaises(ValueError):normalize_nights({'primetime_nights':'bad'})
 def test_controls_tags_and_verification_links_preserve_both_nights(self):
  c=app.test_client();path='/trend-finder?research_view=general&run=analyze&season=2025&primetime_nights=sun&primetime_nights=mon'
  html=c.get(path).text
  self.assertIn('Sunday Night, Monday Night',html)
  for night in ('Thursday Night','Sunday Night','Monday Night','Saturday Night','Friday Night'):self.assertIn(night,html)
  self.assertIn('Nights: Sunday Night, Monday Night',manual_trend_title('/trend-finder?primetime_nights=sun,mon'))
  html=c.get(path+'&action=combinations').text
  urls=re.findall(r'data-evidence-url="([^\"]+)"',html);self.assertTrue(urls)
  for url in urls[:3]:
   p=parse_qs(urlsplit(unescape(url)).query)
   self.assertEqual(p['primetime_nights'],['sun,mon'])
   self.assertEqual(c.get(unescape(url)).status_code,200)
  self.assertEqual(c.get(path+'&primetime_nights=bad').status_code,400)

if __name__=='__main__':unittest.main()
