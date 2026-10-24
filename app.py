from flask import Flask, render_template, request, abort, Response, url_for, redirect
from trend_finder_2 import run_analysis, scan_sunday_matchups, match_upcoming_game, scan_basic_trends, compare_trends, load_finished_games, scan_hot_performance, group_hot_trends, scan_active_streaks, group_active_streaks, evaluate_trend, find_recent_form, find_active_streak
from trend_finder_2 import CSV_FILTER_FIELDS, get_csv_filter_options, scan_grouped_combinations, combination_min_games, describe_combination, find_matching_trend_games, build_trend_evidence, trend_data_status, upcoming_combination_contexts, game_file, get_current_qb_options
import csv
import hashlib
from functools import lru_cache
import calendar
import math
from pathlib import Path
from flask import jsonify
from io import StringIO
from datetime import datetime
import subprocess
import sys
import json
from urllib.request import Request, urlopen


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
from pwa import init_app as init_pwa
init_pwa(app)
from membership import init_membership
init_membership(app)
from community_comments import init_community
init_community(app)
from huddle_leaderboard import init_huddle_leaderboard
init_huddle_leaderboard(app)
from fan_views import bp as fans_bp
app.register_blueprint(fans_bp)
from sunday_scout import scout_bp
app.register_blueprint(scout_bp)
from scout4.web import bp as scout4_bp
app.register_blueprint(scout4_bp)
from expert_beta import init_app as init_expert_beta
init_expert_beta(app)


@lru_cache(maxsize=128)
def static_asset_version(path, modified_ns, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


@app.url_defaults
def version_static_assets(endpoint, values):
    if endpoint != 'static':
        return
    filename = values.get('filename', '')
    if Path(filename).suffix not in {'.css', '.js'}:
        return
    root = Path(app.static_folder).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        return
    try:
        stat = path.stat()
        values.setdefault('v', static_asset_version(str(path), stat.st_mtime_ns, stat.st_size))
    except OSError:
        pass


@app.template_filter('display_trend_filters')
def display_trend_filters(filters):
    labels = []
    for label in filters:
        if label.startswith('Month: '):
            value = label.split(': ', 1)[1]
            if value.isdigit() and 1 <= int(value) <= 12:
                label = f'Month: {calendar.month_name[int(value)]}'
        if label in ('Div Game: 0', 'Div Game: 1'):
            label = 'Division matchup: ' + ('Yes' if label.endswith('1') else 'No')
        labels.append(label)
    return ' | '.join(labels)


@app.template_filter('display_trend_baseline')
def display_trend_baseline(filters):
    names = {'Div Game: 0': 'Non-division games', 'Div Game: 1': 'Division games'}
    return display_trend_filters([names.get(label, label) for label in filters])


@app.route("/", methods=["GET", "POST"])
def home():
    # Render probes HEAD / during port detection; do not run historical scans.
    if request.method == 'HEAD':
        return Response(status=200)
    if request.method == 'POST':
        # Preserve bookmarked legacy analysis forms without changing the new home.
        return redirect(url_for('trend_finder'), code=307)
    from fan_views import data_freshness
    from active_trends import load_highlights
    from emerging_alerts import home_dog_alert
    from hosted_memory import home_context
    context = home_context(lambda: dict(active_highlights=load_highlights(),
        freshness=data_freshness(),emerging_alert=home_dog_alert(Path(__file__).resolve().parent)))
    return render_template("home.html", **context)


@app.route('/hot-trends')
def hot_trends_page():
    from active_trends import load_highlights
    return render_template('hot_trends.html',
                           active_highlights=load_highlights(all_trends=True))


@app.route("/the-plug")
def plug_page():
    if app.config.get("EXPERT_BETA_ENABLED"):
        from expert_beta import dashboard
        return dashboard()
    return app.view_functions['sunday_scout.sunday_scout_page']()


@app.route('/trend-finder/games')
def general_trend_games():
    from general_research import render_general
    selection=request.args.to_dict()
    selection.update(research_view='general',run='analyze',action='analyze')
    selection.pop('evidence',None)
    return render_general(selection,games_page=True)


@app.route("/trend-finder", methods=["GET", "POST"])
def trend_finder():

    form_data=request.form if request.method=='POST' else request.args
    legacy = request.method=='POST' or request.args.get('run')=='analyze'
    research_view=form_data.get('research_view','dogs' if legacy else 'general')
    if research_view=='general':
        from general_research import render_general
        return render_general(form_data)
    if research_view!='dogs':abort(400,description='Choose a valid research view.')
    filter_options = get_csv_filter_options()
    csv_filters = {}
    current_qbs = get_current_qb_options()
    dog_qb_name = ''
    historical_dog_qb_name = ''
    combinations = None
    combination_count = 0
    combination_conditions = []
    summary = None
    matchup_groups = []
    error = None
    season_mode = 'single'
    season = None
    start_season = None
    end_season = None
    location = None
    is_primetime = None
    spread_mode = 'none'
    min_spread = None
    max_spread = None
    exact_spread = None
    active_filters =[]
   

   

    if request.method == 'POST' or request.args.get('run')=='analyze':
        try:
            combination_conditions = json.loads(form_data.get('combination_conditions', '[]'))
            if not isinstance(combination_conditions, list) or len(combination_conditions) > 3 or any(not isinstance(label, str) or ': ' not in label or len(label) > 200 for label in combination_conditions):
                raise ValueError
        except (ValueError, TypeError):
            abort(400, description='Invalid combination conditions.')
        for field in CSV_FILTER_FIELDS:
            value = form_data.get(field, '').strip()
            if value:
                csv_filters[field] = value
                if value not in filter_options[field]:
                    error = f'Choose a CSV value for {field.replace("_", " ")}. '
        dog_qb_name = form_data.get('dog_qb_name', '').strip()
        historical_dog_qb_name = form_data.get('historical_dog_qb_name', '').strip()
        if dog_qb_name and dog_qb_name not in current_qbs:
            error = 'Choose a current-season underdog QB from the dropdown.'
        if historical_dog_qb_name and historical_dog_qb_name not in filter_options['dog_qb_name']:
            error = 'Choose a historical underdog QB from the dropdown.'
        if dog_qb_name and historical_dog_qb_name and dog_qb_name != historical_dog_qb_name:
            error = 'Choose one underdog QB: use either the current or historical dropdown.'
        if dog_qb_name or historical_dog_qb_name:
            csv_filters['dog_qb_name'] = historical_dog_qb_name or dog_qb_name
        season = form_data.get('season', '')
        season_mode = form_data.get('season_mode', 'single')
        single_season_input = form_data.get('season', '')
        start_season_input = form_data.get('start_season', '')
        end_season_input = form_data.get('end_season', '')

        location = form_data.get('location', '')
        primetime = form_data.get('primetime', '')
        
        spread_mode = form_data.get("spread_mode", "none")
        min_spread_input = form_data.get('min_spread', '')
        max_spread_input = form_data.get('max_spread', '')
        exact_spread_input = form_data.get('exact_spread', '')
       
        


        def parse_year(value):
            year = int(value)
            if not 1999 <= year <= datetime.now().year:
                raise ValueError('Choose a season from the available years.')
            return year

        def parse_spread(value):
            spread = float(value)
            if not math.isfinite(spread) or not 0 <= spread <= 25 or spread % 0.5 != 0:
                raise ValueError('Choose a spread from 0 to 25 in half-point steps.')
            return spread

        try:
            if season_mode == 'single':
                season = str(parse_year(single_season_input)) if single_season_input else None
            elif season_mode == 'range':
                if not start_season_input or not end_season_input:
                    raise ValueError('Choose both a start and end season.')
                start_season = parse_year(start_season_input)
                end_season = parse_year(end_season_input)
                if start_season > end_season:
                    raise ValueError('Start season cannot be greater than end season.')
                season = (start_season, end_season)
            else:
                raise ValueError('Choose a valid season filter mode.')
            if spread_mode == 'none':
                pass
            elif spread_mode == 'min':
                min_spread = parse_spread(min_spread_input)
            elif spread_mode == 'max':
                max_spread = parse_spread(max_spread_input)
            elif spread_mode == 'exact':
                exact_spread = parse_spread(exact_spread_input)
            elif spread_mode == 'range':
                min_spread = parse_spread(min_spread_input)
                max_spread = parse_spread(max_spread_input)
                if min_spread > max_spread:
                    raise ValueError('Minimum spread cannot be greater than maximum spread.')
            else:
                raise ValueError('Choose a valid spread filter mode.')
            if location not in ('', 'Home', 'Away') or primetime not in ('', 'yes', 'no'):
                raise ValueError('Choose valid location and primetime filters.')
        except (ValueError, OverflowError):
            error = 'Please choose valid season and spread values; ranges must run from minimum to maximum.'

        if primetime == 'yes':
            is_primetime = True
        elif primetime == 'no':
            is_primetime = False
        else:
            is_primetime = None
        if location == '':
            location = None
        if error is None and form_data.get('action')=='combinations':
            import csv
            with open(game_file,newline='') as source:
                newest=max(int(g['season']) for g in csv.DictReader(source))
            low,high=season if isinstance(season,tuple) else (int(season),int(season)) if season is not None else (newest-4,newest)
            season=(max(low,newest-4),min(high,newest))
            if season[0]>season[1]:
                error=f'Find combinations uses the latest five seasons ({newest-4}–{newest}). Choose a season in that range.'
            else:
                season_mode='range';start_season,end_season=season
        if error is None:
            stats = run_analysis(combination_conditions=combination_conditions, season=season, location=location, is_primetime=is_primetime, min_spread=min_spread, max_spread=max_spread, exact_spread=exact_spread, **csv_filters)
            if form_data.get("action") == "combinations":
                combinations = scan_grouped_combinations(season=season, location=location, is_primetime=is_primetime, min_spread=min_spread, max_spread=max_spread, exact_spread=exact_spread, **csv_filters)
                combinations = [trend for trend in combinations if trend["ats_rate"] >= 55.0 and trend["sample"] >= combination_min_games(season)]
                combination_count = combinations[0].get('retained_count', len(combinations)) if combinations else 0
                combinations = combinations[:30]
            all_games = stats['all_games']

            total_dogs = (
                all_games['home']['total']
                + all_games['away']['total']
            )
            if total_dogs < 10:
                sample_strength = 'Very Small'
            elif total_dogs < 30:
                sample_strength = 'Small'
            elif total_dogs < 100:
                sample_strength = 'Moderate'
            else:
                sample_strength = 'Large'

            dog_wins = (
                all_games['home']['wins']
                + all_games['away']['wins']
            )

            dog_covers = (
                all_games['home']['covers']
                + all_games['away']['covers']
            )

            dog_pushes = (
                all_games['home']['pushes']
                + all_games['away']['pushes']
            )

            win_rate = None
            ats_rate = None
            ats_edge = None
            breakeven_rate = 52.38

            if total_dogs > 0:
                win_rate = (dog_wins / total_dogs) * 100

            dogs_no_push = total_dogs - dog_pushes
            trend =evaluate_trend(stats)
            if trend is None:
                ats_ci_low = None
                ats_ci_high = None
                trend_signal = 'No Data'
            else:
                ats_rate = trend['ats_rate']
                ats_edge = trend['ats_edge']
                ats_ci_low = trend['ci_low']
                ats_ci_high = trend['ci_high']
                trend_signal = trend['signal']
            
            

            
            summary = {
                "games": all_games["games"],
                "dogs": total_dogs,
                "wins": dog_wins,
                "covers": dog_covers,
                "pushes": dog_pushes,
                "pickems": stats['all_games']['pickems']['total'],
                "win_rate": win_rate,
                "ats_rate": ats_rate,
                "sample_strength": sample_strength,
                "ats_edge": ats_edge,
                "ats_ci_low": ats_ci_low,
                "ats_ci_high": ats_ci_high,
                "trend_signal": trend_signal
            }
    if summary is not None and combinations is None:
        from home_results import matching_game_groups
        matchup_groups = matching_game_groups(
            combination_conditions=combination_conditions, season=season, location=location, is_primetime=is_primetime,
            min_spread=min_spread, max_spread=max_spread,
            exact_spread=exact_spread, **csv_filters)
    if season_mode == "single" and season:
        active_filters.append(f"Season {season}")

    elif season_mode == "range" and start_season is not None and end_season is not None:
        active_filters.append(f"{start_season}–{end_season}")

    if location is not None:
        active_filters.append(f"{location} Dogs")

    if is_primetime is True:
        active_filters.append("Primetime")
    elif is_primetime is False:
        active_filters.append("Non-Primetime")

    if exact_spread is not None:
        active_filters.append(f"Spread {exact_spread}")

    elif min_spread is not None and max_spread is not None:
        active_filters.append(f"Spread {min_spread}–{max_spread}")

    elif min_spread is not None:
        active_filters.append(f"Spread {min_spread}+")

    elif max_spread is not None:
        active_filters.append(f"Spread ≤ {max_spread}")
    if combinations is not None:
        for trend in combinations:
            trend['games_url'] = url_for('combination_details',
                conditions=json.dumps(trend['filters']),
                selection=json.dumps(dict(season=season, location=location, is_primetime=is_primetime,
                                          min_spread=min_spread, max_spread=max_spread,
                                          exact_spread=exact_spread, **csv_filters)))
            for related in trend.get('related', []):
                related['games_url'] = url_for('combination_details', conditions=json.dumps(related['filters']),
                    selection=json.dumps(dict(season=season, location=location, is_primetime=is_primetime,
                        min_spread=min_spread, max_spread=max_spread, exact_spread=exact_spread, **csv_filters)))
            trend['description'] = describe_combination(
                trend, season=season, location=location, is_primetime=is_primetime,
                min_spread=min_spread, max_spread=max_spread, exact_spread=exact_spread,
                **csv_filters)
    active_filters.extend(f"{'Underdog QB' if field == 'dog_qb_name' else field.replace('_', ' ').title()}: {value}" for field, value in csv_filters.items())
    from home_results import qb_summaries, results_freshness
    filter_chips=[]
    if combination_conditions:
        filter_chips.append(dict(label=display_trend_filters(combination_conditions), fields=['combination_conditions']))
    if season_mode=='single' and season:filter_chips.append(dict(label=f'Season {season}',fields=['season']))
    elif start_season is not None and end_season is not None:filter_chips.append(dict(label=f'{start_season}–{end_season}',fields=['start_season','end_season']))
    if location:filter_chips.append(dict(label=f'{location} Dogs',fields=['location']))
    if is_primetime is not None:filter_chips.append(dict(label='Primetime' if is_primetime else 'Non-Primetime',fields=['primetime']))
    if any(v is not None for v in (min_spread,max_spread,exact_spread)):filter_chips.append(dict(label=(f'Exact spread: +{exact_spread:g}' if exact_spread is not None else f'Spread: {min_spread:g}–{max_spread:g}' if min_spread is not None and max_spread is not None else f'Spread: +{min_spread:g} or more' if min_spread is not None else f'Spread: up to +{max_spread:g}'),fields=['spread_mode','min_spread','max_spread','exact_spread']))
    for key,value in csv_filters.items():filter_chips.append(dict(label=f"{'QB' if key=='qb_name' else 'Underdog QB' if key=='dog_qb_name' else key.replace('_',' ').title()}: {value}",fields=['dog_qb_name','historical_dog_qb_name'] if key=='dog_qb_name' else [key]))
    from saved_trends import manual_trend_title
    manual_search_url=url_for('trend_finder',run='analyze',**{k:v for k,v in form_data.items() if v and k not in ('run','action','csrf_token')})
    from active_trends import load_highlights
    return render_template(
        "index.html",
        active_highlights=load_highlights(),
        manual_search_url=manual_search_url,manual_search_title=manual_trend_title(manual_search_url),
        filter_chips=filter_chips,qb_summaries=qb_summaries(matchup_groups),results_freshness=results_freshness(),
        filter_options=filter_options,
        csv_filters=csv_filters,
        more_filters_open=bool(historical_dog_qb_name) or any(field not in {'dog_qb_name', 'game_type'} for field in csv_filters),
        current_qbs=current_qbs,
        dog_qb_name=dog_qb_name,
        historical_dog_qb_name=historical_dog_qb_name,
        combination_conditions=combination_conditions,
        combinations=combinations,
        data_status=trend_data_status() if combinations is not None else None,
        combination_count=combination_count,
        combination_minimum=combination_min_games(season),
        summary=summary,
        matchup_groups=matchup_groups,
        season=season,
        season_mode=season_mode,
        start_season=start_season,
        end_season=end_season,
        location=location,
        is_primetime=is_primetime,
        spread_mode=spread_mode,
        min_spread=min_spread,
        max_spread=max_spread,
        exact_spread=exact_spread,
        error=error,
        active_filters=active_filters
    )


@app.route('/trend-games')
@app.route('/combination-details', endpoint='combination_details')
def trend_games():
    try:
        conditions = json.loads(request.args.get('conditions', '[]'))
        selection = json.loads(request.args.get('selection', '{}'))
        allowed = set(CSV_FILTER_FIELDS) | {'season', 'location', 'is_primetime', 'min_spread', 'max_spread', 'exact_spread', 'dog_qb_name'}
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 3:
            raise ValueError
        if any(not isinstance(label, str) or ': ' not in label or len(label) > 200 for label in conditions):
            raise ValueError
        if not isinstance(selection, dict) or set(selection) - allowed:
            raise ValueError
        season = selection.pop('season', None)
        if isinstance(season, list):
            if len(season) != 2 or any(type(year) is not int for year in season) or season[0] > season[1]:
                raise ValueError
            season = tuple(season)
        elif season is not None:
            season = int(season)
        if selection.get('location') not in (None, 'Home', 'Away'):
            raise ValueError
        if selection.get('is_primetime') is not None and type(selection['is_primetime']) is not bool:
            raise ValueError
        for key, value in selection.items():
            if key in ('min_spread', 'max_spread', 'exact_spread') and value is not None:
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError
            elif (key in CSV_FILTER_FIELDS or key == 'dog_qb_name') and value is not None and not isinstance(value, (str, int, float)):
                raise ValueError
        page = int(request.args.get('page', '1'))
        if page < 1:
            raise ValueError
    except (ValueError, TypeError):
        abort(400, description='Invalid trend or selection.')
    games = find_matching_trend_games(conditions, season=season, **selection)
    status = trend_data_status()
    evidence = build_trend_evidence(games, status['current_season'])
    page_count = max(1, math.ceil(len(games) / 25))
    if page > page_count:
        abort(404)
    def page_url(number):
        return url_for('combination_details', conditions=request.args['conditions'],
                       selection=request.args.get('selection', '{}'), page=number)
    # Rebuild from the selection instead of trusting record values in a URL.
    groups = scan_grouped_combinations(season=season, **selection)
    detail = next((group for group in groups if set(group['filters']) == set(conditions)), None)
    if detail is None:
        record = evidence['periods'][0]
        wins = sum((game['home_score'] > game['away_score'] if game['dog_team'] == game['home_team']
                    else game['away_score'] > game['home_score']) for game in games)
        zero = dict(total=0, wins=0, covers=0, pushes=0)
        stats = evaluate_trend({'all_games': {
            'home': dict(total=record['sample'], wins=wins, covers=record['ats_wins'], pushes=record['ats_pushes']),
            'away': zero,
        }})
        detail = dict(stats or {}, filters=conditions, related=[], equivalent_filters=[],
                      status='Emerging' if len(games) < 30 else 'Historical sample',
                      validation_label='Exploratory historical pattern')
    if not games:
        detail['description'] = 'No completed games match these conditions.'
    elif detail.get('ats_rate') is None:
        detail['description'] = f'{len(games)} games match these conditions, but all were pushes; there is no ATS cover rate.'
    else:
        detail['description'] = describe_combination(detail, season=season, **selection)
    for related in detail.get('related', []):
        related['games_url'] = url_for('combination_details', conditions=json.dumps(related['filters']),
            selection=json.dumps(dict(season=season, **selection)))
    scope_labels = [f'{key.replace("_", " ").title()}: {value}' for key, value in selection.items() if value is not None]
    verification_fields = {key: value for key, value in selection.items() if value is not None}
    if 'is_primetime' in verification_fields:
        verification_fields['primetime'] = 'yes' if verification_fields.pop('is_primetime') else 'no'
    if 'dog_qb_name' in verification_fields:
        verification_fields['historical_dog_qb_name'] = verification_fields.pop('dog_qb_name')
    verification_fields['spread_mode'] = 'exact' if selection.get('exact_spread') is not None else 'range' if selection.get('min_spread') is not None and selection.get('max_spread') is not None else 'min' if selection.get('min_spread') is not None else 'max' if selection.get('max_spread') is not None else 'none'
    verification_fields['season_mode'] = 'range' if isinstance(season, tuple) else 'single'
    if isinstance(season, tuple):
        verification_fields.update(start_season=season[0], end_season=season[1])
    elif season is not None:
        verification_fields['season'] = season
    return render_template('trend_games.html', verification_fields=verification_fields, conditions=conditions, scope_labels=scope_labels,
                           season=season, trend=detail, games=games[(page-1)*25:page*25], evidence=evidence,
                           data_status=status, page=page, page_count=page_count,
                           previous_url=page_url(page-1) if page > 1 else None,
                           next_url=page_url(page+1) if page < page_count else None)

def group_early_watch(watchlist, games):
    grouped = []

    watchlist = sorted(
        watchlist,
        key=lambda t: (
            max(
                t['current_su_rate'] - t['historical_su_rate'],
                t['current_ats_rate'] - t['historical_ats_rate']
            ),
            t["dog_no_push"]),
        reverse=True
    )

    for trend in watchlist:
        matching_games = set()

        for game in games:

            if game["dog_location"] != trend["location"]:
                continue

            if game["is_primetime"] != trend["primetime"]:
                continue

            minimum = trend["min_spread"]
            maximum = trend["max_spread"]

            if minimum is not None and game["dog_spread"] < minimum:
                continue

            if maximum is not None and game["dog_spread"] > maximum:
                continue

            game_id = (
                game["gameday"],
                game["away_team"],
                game["home_team"]
            )

            matching_games.add(game_id)

        if not matching_games:
            continue

        matched = False

        for leader in grouped:

            if leader["location"] != trend["location"]:
                continue

            if leader["primetime"] != trend["primetime"]:
                continue

            existing_games = leader["_games"]

            shared = len(matching_games & existing_games)
            combined = len(matching_games | existing_games)

            similarity = shared / combined

            if similarity >= 0.75:
                leader["related"].append(trend)
                matched = True
                break

        if not matched:
            leader = trend.copy()
            leader["_games"] = matching_games
            leader["related"] = []
            grouped.append(leader)

    for leader in grouped:
        del leader["_games"]

    return grouped

@app.route("/trends")
def trends_page():
    from active_trends import load_highlights
    current = scan_basic_trends(season='2026')
    historical = scan_basic_trends(season=(1999, 2025))
    comparisons = compare_trends(current, historical)
    comparisons.sort(
        key=lambda trend: (
            2 if trend['ats_difference'] > 0
            else 1 if trend['ats_difference'] < 0
            else 0,
            trend['dog_no_push'] >= 10,
            abs(trend['ats_difference']),
            trend['dog_no_push']), reverse=True)
    comparison_sections = [
    (
        "📈 Above Historical ATS",
        [t for t in comparisons if t["ats_difference"] > 0]
    ),
    (
        "📉 Below Historical ATS",
        [t for t in comparisons if t["ats_difference"] < 0]
    ),
    (
        "📝 Matches Historical ATS",
        [t for t in comparisons if t["ats_difference"] == 0]
    )
]
    watchlist = []

    for trend in comparisons:
        sample = trend['current_sample']

        if not 3 <= sample < 15:
            continue
        su_rate = trend['current_su_rate']
        ats_rate = trend['current_ats_rate']
        highest_rate = max(su_rate, ats_rate)

        if highest_rate >= 100:
            alert = 'Gravy Train 🚂'
        elif highest_rate >=90:
            alert = 'Don"t Look Now..🔥'
        elif highest_rate >= 80:
            alert = 'Hot Start 👀'
        elif highest_rate >= 70:
            alert = 'Early Watch 🫣'
        else:
            continue
        trend['alert'] = alert
        watchlist.append(trend)
    
    games = load_finished_games()

    watchlist = group_early_watch(
        [trend for trend in watchlist if trend['spread'] == 'All Spreads'], games
    )

    broad_comparisons = [trend for trend in comparisons if trend['spread'] == 'All Spreads']
    hot_trends = scan_hot_performance(
        games, broad_comparisons, window=5
    )
    hot_groups = group_hot_trends(hot_trends)
    active_streaks = scan_active_streaks(games,broad_comparisons, min_streak=3)
    streak_groups = group_active_streaks(active_streaks)
    return render_template(
        'trends.html',active_highlights=load_highlights(),
        comparisons=comparisons,
        watchlist=watchlist,
        hot_groups=hot_groups,
        hot_trends=hot_trends, 
        streak_groups=streak_groups, 
        comparison_sections=comparison_sections,
        )

@app.route("/trend-details")
def trend_details():
    location = request.args.get("location")
    prime = request.args.get('prime')
    spread = request.args.get('spread')

    if (
        location not in ('Home', 'Away')
        or prime not in ("yes", "no")
        or not spread
    ):
        abort(400)
    current = scan_basic_trends(season='2026')
    historical = scan_basic_trends(season=(1999, 2025))

    comparisons = compare_trends(current, historical)

    trend = next(
        (
            t for t in comparisons
            if t['location'] == location
            and t['primetime'] == (prime == 'yes')
            and t['spread'] == spread
        ),
        None
    )
    if trend is None:
        abort(404)
    
    games = load_finished_games()

    filters = {
        "location": trend["location"],
        "is_primetime": trend["primetime"],
        "min_spread": trend["min_spread"],
        "max_spread": trend["max_spread"],
        "metric": "ats"
    }

    recent = find_recent_form(
        games,
        window=5,
        **filters
    )

    streak = find_active_streak(
        games,
        **filters
    )

    return render_template(
        "trend_details.html",
        trend=trend,
        recent=recent,
        streak=streak
    )

def _build_historical_matchups(window, archive):
    start_year = 1999 if window == 'all' else 2026 - int(window)
    current = scan_basic_trends(season="2026")

    historical = scan_basic_trends(
        season=(start_year, 2025)
    )

    comparisons = compare_trends(current, historical)
    from site_views import public_matchups
    if archive:
        games=scan_sunday_matchups(comparisons);pending=[]
        # Resolve archived cards through authoritative schedule IDs, never guessed IDs.
        with Path(game_file).open(newline='') as source:
            archive_ids = {(row['gameday'],row['away_team'],row['home_team']):row['game_id']
                           for row in csv.DictReader(source)}
        for game in games:
            game['game_id'] = archive_ids.get((game.get('gameday'),game['away_team'],game['home_team']))
    else:
        games,pending=public_matchups(comparisons,Path(__file__).resolve().parent)

    historical_lookup = {
        (trend['location'], trend['primetime'], trend['spread']): trend for trend  in historical
    }
    for game in games:
        candidates = [
            trend for trend in game['matches']
            if trend['spread'] != 'All Spreads'
            and trend['historical_sample'] >30
            and trend['historical_ci_low'] is not None
        ]
        candidates.sort(
            key=lambda trend: trend['historical_ci_low'],
            reverse=True
        )
        game['top_trends'] = candidates[:3]
        
        spread = game["dog_spread"]

        if spread <= 3:
            band = "0.5-3"
        elif spread <= 6.5:
            band = "3.5-6.5"
        elif spread <= 9.5:
            band = "7-9.5"
        else:
            band = "10+"

        ranking_trend = historical_lookup.get((
            game["dog_location"],
            game["is_primetime"],
            band
        ))

        game["ranking_trend"] = ranking_trend

        game["ranking_score"] = (
            ranking_trend["ci_low"]
            if ranking_trend is not None
            and ranking_trend["sample"] >= 30
            and ranking_trend["ci_low"] is not None
            else -1
        )

    games.sort(key=lambda game: game['ranking_score'], reverse=True)
    scores = [game['ranking_score'] for game in games]
    previous_score = None

    for position, game in enumerate(games, start=1):
        score = game['ranking_score']
        if score < 0:
            game['rank'] = None
            game['tied'] = False
            continue
        if score != previous_score:
            rank = position

        game['rank'] = rank
        game['tied'] = scores.count(score) > 1
        previous_score = score

    return dict(games=games,pending=pending,selected_window=window,start_year=start_year,archive=archive,
        slate_labels=sorted({f"{parts[0]} Week {int(parts[1])}" for game in games+pending
            if game.get('game_id') and len(parts:=game['game_id'].split('_'))>=2
            and parts[0].isdigit() and parts[1].isdigit()}))


@app.route("/sunday")
def sunday_page():
    from historical_window_cache import request_key, window_context
    window, archive = request_key()
    context = window_context(lambda: _build_historical_matchups(window,archive))
    games = context['games']
    if request.args.get("download") == "1":

        output = StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "recorded_at", "window",
            "away_team", "home_team",
            "dog_team", "dog_spread",
            "dog_location", "primetime",
            "ranking_band", "historical_ats",
            "historical_games", "lower_bound",
            "rank", "ats_result", "su_result"
        ])

        recorded_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        for game in games:
            trend = game["ranking_trend"]

            writer.writerow([
                recorded_at,
                window,
                game["away_team"],
                game["home_team"],
                game["dog_team"],
                game["dog_spread"],
                game["dog_location"],
                game["is_primetime"],
                trend["spread"] if trend else "",
                trend["ats_rate"] if trend else "",
                trend["sample"] if trend else "",
                trend["ci_low"] if trend else "",
                game["rank"],
                "",
                ""
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                f"attachment; filename=upcoming_matchups_{datetime.now().date()}_{window}.csv"
            }
        )

    return render_template('sunday.html', **context)

@app.route("/sunday-results")
def sunday_results_page():
    from weekly_results import build_results
    view=build_results(Path(__file__).resolve().parent,request.args.get('week'))
    return render_template('sunday_results.html',**view)


@app.route("/api/backtests")
def backtest_data():

    file_path = Path(__file__).with_name("backtest_summary.csv")
    results = []

    with open(file_path, newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:

            top_covers = int(row["top_covers"])
            top_losses = int(row["top_losses"])

            bottom_covers = int(row["bottom_covers"])
            bottom_losses = int(row["bottom_losses"])

            top_total = top_covers + top_losses
            bottom_total = bottom_covers + bottom_losses

            results.append({
                "year": int(row["test_year"]),
                "window": row["window"],
                "games_evaluated": int(row["games_evaluated"]),

                "top_ats": round(
                    top_covers / top_total * 100, 1
                ) if top_total else None,

                "bottom_ats": round(
                    bottom_covers / bottom_total * 100, 1
                ) if bottom_total else None
            })

    return jsonify(results)
@app.route("/backtests")
def backtest_page():
    return render_template('backtests.html')


@app.route("/conspiracy-dungeon/events", methods=["POST"])
def add_anomaly_event():
    from anomaly_store import add_event
    try:
        event = add_event(Path(__file__).resolve().parent, request.form)
    except ValueError as exc:
        abort(400, description=str(exc))
    return redirect(url_for("conspiracy_dungeon_page", panel="anomalies",
                            category=event["category"], anomaly_year=event["event_date"][:4],
                            mobile_results="1" if request.form.get("mobile_results") == "1" else None))

@app.route("/conspiracy-dungeon")
def conspiracy_dungeon_page():
    from dungeon_results import build_view

    archive_week = request.args.get("week")
    archive_stage = request.args.get("stage", "REG")
    if archive_week is not None and archive_week != "all":
        if not archive_week.isdigit() or not 1 <= int(archive_week) <= 22:
            abort(400)
    if archive_stage not in {"REG", "WC", "DIV", "CON", "SB"}:
        abort(400)
    anomaly_year = request.args.get("anomaly_year")
    if anomaly_year is not None and anomaly_year != "all" and (not anomaly_year.isdigit() or not 1999 <= int(anomaly_year) <= 2100):
        abort(400)
    view = build_view(request.args.get("panel", "money"),
                      archive_week=archive_week, archive_stage=archive_stage,
                      anomaly_category=request.args.get("category", "world"), anomaly_year=anomaly_year)
    return render_template("conspiracy_dungeon.html", view=view)



@app.get('/market')
def market_page():
    # Keep existing bookmarks working without a duplicate spreads-and-totals page.
    return redirect(url_for('plug_page'), code=302)

@app.context_processor
def site_week_context():
    from site_week import active_week
    from market_views import read
    return {'current_site_week':active_week(read(Path(__file__).resolve().parent/'nfl_games.csv'))}

app.config['METHODOLOGY_ENABLED']=True
@app.get('/about')
def methodology_page():
    return render_template('methodology.html')

from seo import init_seo
init_seo(app)

if __name__ == '__main__':
    app.run(port=5001)