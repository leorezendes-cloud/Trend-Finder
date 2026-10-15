"""Search metadata and discovery routes; never changes visible page content."""
import csv,re
from pathlib import Path
from xml.etree import ElementTree as ET
from flask import current_app,has_request_context,request,Response

PAGES={
 'methodology_page':('/about','About & Methodology | NFL Research | Gravy Train','Learn how Gravy Train researches NFL trends, creates locked Plug picks, captures shared member lines, and grades ATS and over/under records.'),
 'home':('/', 'Discover NFL Trends & Predictions | Gravy Train', 'Discover NFL trends with Trendfindah 3000, get The Plug’s locked predictions, and investigate betting patterns and conspiracy theories in the Conspiracy Dungeon.'),
 'trend_finder':('/trend-finder','Trendfindah 3000 | NFL Trend Finder | Gravy Train','Discover NFL trends with Trendfindah 3000, an NFL trend finder. Research historical ATS patterns by season, spread, team, coach, quarterback, and primetime, and save your searches.'),
 'trends_page':('/trends','Discover NFL Trends, ATS Patterns & Streaks | Gravy Train','Discover NFL trends and ATS streaks with Trendfindah 3000: compare historical records, sample sizes, recent performance, and upcoming matchups.'),
 'sunday_page':('/sunday','Upcoming NFL Matchups & Spreads | Gravy Train','Review this week’s NFL matchups, saved spreads, kickoff times, and historical underdog trends. Compare teams, challenge The Plug, and see how you do this week.'),
 'market_page':('/market','Upcoming NFL Spreads & Totals | Gravy Train','See the latest verified saved NFL spreads and over/under totals for upcoming games, with quote timestamps and links to team comparisons.'),
 'plug_page':('/the-plug','NFL ATS & Over/Under Picks | The Plug | Gravy Train','See The Plug’s locked NFL ATS and over/under predictions, projected scores, original lines, and recorded results, powered by Scout 4.0.'),
 'sunday_results_page':('/sunday-results','Weekly NFL Scores & ATS Pick Results | Gravy Train','Review weekly NFL final scores, teams’ ATS records as underdogs, matchup outcomes, and The Plug’s locked ATS and over/under pick results.'),
 'scout4.teams_page':('/scout4/teams','NFL Team Stats & Comparisons | Gravy Train','Compare NFL team offense and defense, ATS records, recent form, passing, rushing, and game logs using saved statistics.'),
 'scout4.players_page':('/scout4/players','NFL Player Stats & Leaders | Gravy Train','Explore NFL player statistics, passing, rushing, receiving, and defensive leaders with season and team filters.'),
 'scout4.ratings_page':('/scout4/ratings','NFL Team Ratings | Scout 4.0 | Gravy Train','Explore NFL team ratings and matchup research powered by Scout 4.0, with saved data and transparent model information.'),
 'fans.fantasy':('/fantasy','NFL Fantasy Football PPR Stats | Gravy Train','Explore NFL fantasy football PPR statistics and player performance using saved season data.'),
 'fans.prediction_results':('/predictions/results','NFL Prediction Results & Pick Records | Gravy Train','Track The Plug’s NFL ATS and over/under results. Picks are saved before kickoff and graded against their original lines and verified final scores.'),
 'conspiracy_dungeon_page':('/conspiracy-dungeon','NFL Conspiracies & Betting Patterns | Conspiracy Dungeon','Explore NFL conspiracy theories through public betting splits, line movement, referee trends, and unusual game results in the Conspiracy Dungeon.'),
}
ALIASES={'sunday_scout.sunday_scout_page':'plug_page'}
TEAMS={'ARI':'Arizona Cardinals','ATL':'Atlanta Falcons','BAL':'Baltimore Ravens','BUF':'Buffalo Bills','CAR':'Carolina Panthers','CHI':'Chicago Bears','CIN':'Cincinnati Bengals','CLE':'Cleveland Browns','DAL':'Dallas Cowboys','DEN':'Denver Broncos','DET':'Detroit Lions','GB':'Green Bay Packers','HOU':'Houston Texans','IND':'Indianapolis Colts','JAX':'Jacksonville Jaguars','KC':'Kansas City Chiefs','LA':'Los Angeles Rams','LAC':'Los Angeles Chargers','LV':'Las Vegas Raiders','MIA':'Miami Dolphins','MIN':'Minnesota Vikings','NE':'New England Patriots','NO':'New Orleans Saints','NYG':'New York Giants','NYJ':'New York Jets','PHI':'Philadelphia Eagles','PIT':'Pittsburgh Steelers','SEA':'Seattle Seahawks','SF':'San Francisco 49ers','TB':'Tampa Bay Buccaneers','TEN':'Tennessee Titans','WAS':'Washington Commanders'}
IMAGE='/static/Images/Branding/gravy-train-branding/gravy-train/gravy-train-icon.png'


def origin():
    # Membership startup validates this trusted configuration; never use Host headers.
    return current_app.config.get('PUBLIC_ORIGIN','https://trendfindah.com').rstrip('/')


def metadata():
    endpoint=ALIASES.get(request.endpoint,request.endpoint)
    page=PAGES.get(endpoint)
    if endpoint=='fans.matchup':
        game_id=(request.view_args or {}).get('game_id','')
        match=re.fullmatch(r'(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)',game_id)
        if match:
            year,week,away,home=match.groups();away=TEAMS.get(away,away);home=TEAMS.get(home,home)
            page=(request.path,f'{away} vs {home} | NFL Week {int(week)}, {year} | Gravy Train',f'Compare {away} and {home} for {year} NFL Week {int(week)}: team statistics, saved ATS and total predictions, and a chance to see how you do this week.')
    public=bool(page) and not request.args and request.method in ('GET','HEAD')
    path,title,description=page or ('',None,'Explore your Gravy Train account, NFL research, member picks, and saved matchup information.')
    return {'title':title,'description':description,'canonical':origin()+path if page else None,
            'indexable':public,'image':origin()+IMAGE,'origin':origin()}


def init_seo(app):
    if app.config.get('SEO_CONFIGURED'):return
    app.config['SEO_CONFIGURED']=True
    app.config.setdefault('SEO_ENABLED',True)

    @app.context_processor
    def search_metadata():
        if not has_request_context() or not app.config['SEO_ENABLED']:return {}
        return {'seo':metadata()}

    @app.after_request
    def search_indexing(response):
        if response.status_code>=400 or response.mimetype=='text/html' and not metadata()['indexable']:
            response.headers['X-Robots-Tag']='noindex, follow'
        return response

    @app.get('/robots.txt')
    def robots_txt():
        return Response(f'User-agent: *\nAllow: /\n\nSitemap: {origin()}/sitemap.xml\n',mimetype='text/plain')

    @app.get('/sitemap.xml')
    def sitemap_xml():
        paths={page[0] for page in PAGES.values()}
        source=Path(app.root_path)/'nfl_games.csv'
        if source.exists():
            with source.open(newline='',encoding='utf-8-sig') as stream:games=list(csv.DictReader(stream))
            years=[int(game['season']) for game in games if game.get('season','').isdigit() and game.get('game_type')=='REG']
            latest=max(years,default=0)
            for game in games:
                if game.get('season')==str(latest) and game.get('game_type')=='REG' and re.fullmatch(r'\d{4}_\d{2}_[A-Z]+_[A-Z]+',game.get('game_id','')):
                    paths.add('/matchup/'+game['game_id'])
        namespace='http://www.sitemaps.org/schemas/sitemap/0.9';ET.register_namespace('',namespace)
        root=ET.Element('{'+namespace+'}urlset')
        for path in sorted(paths):
            entry=ET.SubElement(root,'{'+namespace+'}url');ET.SubElement(entry,'{'+namespace+'}loc').text=origin()+path
        response=Response(ET.tostring(root,encoding='utf-8',xml_declaration=True),mimetype='application/xml')
        response.headers['Cache-Control']='public, max-age=3600'
        return response
