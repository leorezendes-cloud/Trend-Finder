"""Read-only editorial cases. No collectors, model calls, or results writes."""
import json
import re
from functools import lru_cache
from pathlib import Path
from flask import Blueprint, abort, render_template, request, url_for

TITLE = 'The Case Files'  # Display branding only; preserve stable anomaly routes and case URLs.
CATEGORIES = {
    'calls': 'Controversial Calls',
    'blunders': 'What Were They Thinking?',
    'analytics': 'Analytics Gone Wrong?',
    'coincidences': 'Strange Coincidences',
    'oddities': 'Statistical Oddities',
    'bad-beats': 'Bad Beats',
}
ROOT = Path(__file__).resolve().parent / 'research' / 'investigations'
bp = Blueprint('investigations', __name__)


def read_index():
    # Small summaries only. Full files are opened only on individual case requests.
    return json.loads((ROOT / 'index.json').read_text())


def library_view(args):
    rows = read_index()
    tool = args.get('tool', '')
    if tool not in {'', 'international', 'statistics', 'notes'}:
        abort(400, description='Unknown research tool.')
    latest = max(c['season'] for c in rows)
    season = args.get('case_season', str(latest))
    years = sorted({c['season'] for c in rows}, reverse=True)
    if season not in {'all', 'archive', *(str(y) for y in years)}:
        abort(400, description='Unknown investigation season.')
    category = args.get('case_category', 'all')
    if category not in {'all', *CATEGORIES}:
        abort(400, description='Unknown investigation category.')
    query = args.get('q', '').strip()[:120]
    sort = args.get('sort', 'featured')
    if sort not in {'featured', 'newest', 'oldest'}:
        abort(400, description='Unknown investigation sort.')
    selected = [c for c in rows if season == 'all' or
                (season == 'archive' and c['season'] < latest) or str(c['season']) == season]
    counts = {key: sum(key in c['categories'] for c in selected) for key in CATEGORIES}
    selected = [c for c in selected if (category == 'all' or category in c['categories']) and
                (not query or query.casefold() in (' '.join([c['title'], c['teams'], c['summary']])).casefold())]
    selected.sort(key=lambda c: (bool(c['featured']) if sort == 'featured' else False, c['date'], c['slug']), reverse=sort != 'oldest')
    featured = next((c for c in selected if c['featured']), None) if sort == 'featured' else None
    def link(**changes):
        values = dict(panel='anomalies', case_season=season, case_category=category, q=query,
                      sort=sort, mobile_results=args.get('mobile_results'), tool=tool or None)
        values.update(changes)
        return url_for('conspiracy_dungeon_page', **values)
    research = research_view(tool, args, latest) if tool else None
    return dict(tool=tool, research=research, title=TITLE, cards=[c for c in selected if c != featured], featured=featured,
                count=len(selected), total=len(rows), latest=latest, years=years, season=season,
                category=category, categories=CATEGORIES, counts=counts, query=query, sort=sort, link=link)


@bp.get('/conspiracy-dungeon/investigations/<slug>')
def case_page(slug):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
        abort(404)
    rows = read_index()
    match = next((c for c in rows if c['slug'] == slug), None)
    if match is None:
        abort(404)
    case = json.loads((ROOT / (slug + '.json')).read_text())
    related = [c for c in rows if c['slug'] != slug and set(c['categories']) & set(case['categories'])][:3]
    return render_template('investigation_case.html', case=case, categories=CATEGORIES,
                           library_title=TITLE, related=related)


RESEARCH_TOOLS = {'international': 'International field notes',
                  'statistics': 'By the numbers', 'notes': 'Sourced event log'}


def research_view(tool, args, latest):
    year = args.get('research_year', str(latest))
    if year != 'all' and (not year.isdigit() or not 1999 <= int(year) <= latest):
        abort(400, description='Unknown research season.')
    category = {'international': 'world', 'statistics': 'game'}.get(tool, args.get('event_category', 'team'))
    if category not in {'game', 'world', 'player', 'team'}:
        abort(400, description='Unknown event category.')
    anomaly_type = args.get('anomaly_type', 'all')
    if anomaly_type not in {'all', 'High Penalty Count', 'High scoring', 'Large winning margin'}:
        abort(400, description='Unknown statistical filter.')
    root = ROOT.parent.parent
    names = ('nfl_games.csv', 'anomaly_events.csv', 'world_event_notes.csv',
             'game_penalty_stats.csv', 'referee_assignments.csv',
             'public_money_snapshots.csv', 'manual_spread_overrides.csv',
             'research_qb_corrections.csv', 'nfl_games_update_status.json')
    stamps = tuple((name, (root/name).stat().st_mtime_ns, (root/name).stat().st_size)
                   for name in names if (root/name).exists())
    data = _research_data(str(root), category, year, stamps)
    events = [e for e in data['events'] if tool != 'statistics' or anomaly_type == 'all' or e['title'] == anomaly_type]
    # Pagination keeps historical views compact; full original data stays in the analyzer.
    try:
        page = int(args.get('research_page', '1'))
    except ValueError:
        abort(400)
    rows = data['international'] if tool == 'international' else events
    pages = max(1, (len(rows)+11)//12)
    if not 1 <= page <= pages:
        abort(400, description='Unknown research page.')
    return dict(data=data, rows=rows[(page-1)*12:page*12], total=len(rows),
                year=year, category=category, anomaly_type=anomaly_type,
                page=page, pages=pages, title=RESEARCH_TOOLS[tool])


@lru_cache(maxsize=2)
def _research_data(root, category, year, stamps):
    """Bounded, file-versioned cache; never runs until a research tool is opened."""
    import csv
    from pregame_lines import effective_rows
    from anomaly_analysis import build_anomalies
    root = Path(root)
    # Saved finals only: research must never refresh a live score feed on request.
    with (root/'nfl_games.csv').open(newline='', encoding='utf-8-sig') as handle:
        games = {row['game_id']: row for row in effective_rows(
            csv.DictReader(handle), root/'nfl_games.csv', include_scores=False)}
    return build_anomalies(root, games, year if year != 'all' else '2026', category, year)
