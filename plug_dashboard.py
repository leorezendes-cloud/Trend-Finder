"""Read-only combined forecast cards; original models and archived lines stay intact."""
import csv
import math
from pathlib import Path
from flask import url_for
from expert_beta import instant
from public_pick_market import matchup_public_market
from plug_line_movement import compare_line

ROOT = Path(__file__).resolve().parent


def legacy_records():
    from forecast_history import official_sources
    return list(official_sources(ROOT).values())


def _completed_games(root):
    """Read exact-game finals without touching frozen forecasts or grades."""
    path = root / 'nfl_games.csv'
    if not path.exists():
        return {}
    from score_finals import public_final_rows
    with path.open(newline='', encoding='utf-8-sig') as stream:
        rows = public_final_rows(list(csv.DictReader(stream)), path)
    found = {}
    for row in rows:
        try:
            away, home = (float(row[key]) for key in ('away_score', 'home_score'))
            margin = float(row['result'])
            if (not all(math.isfinite(v) and v >= 0 for v in (away, home))
                    or not away.is_integer() or not home.is_integer()
                    or abs(margin - (home-away)) > 1e-8):
                continue
            game_id = row['game_id']
            if (game_id in found or row.get('away_team') != game_id.split('_')[-2]
                    or row.get('home_team') != game_id.split('_')[-1]):
                found.pop(game_id, None)
                continue
            found[game_id] = (int(away), int(home))
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return found


def _grade_selection(side, quote, away, home, *, spread):
    """Results use the immutable quoted line, never the current live market."""
    if not side or not quote:
        return None
    try:
        if spread:
            if side not in (quote['side_a'], quote['side_b']):
                return None
            line = float(quote['line_a'] if side == quote['side_a'] else quote['line_b'])
            edge = (away-home if side == quote['side_a'] else home-away) + line
        else:
            if side not in ('Over', 'Under'):
                return None
            line = float(quote['line_a'])
            edge = (away + home - line) * (1 if side == 'Over' else -1)
        if not math.isfinite(edge):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return 'Push' if abs(edge) < 1e-8 else ('Win' if edge > 0 else 'Loss')


def _attach_final(item, scores):
    if scores is None:
        return
    away, home = scores
    item['final_score'] = {'away': away, 'home': home}
    quotes = item.get('locked_quotes') or {}
    picks = item.get('saved_picks') or {}
    expert = item.get('expert_picks') or {}
    expert_quotes = item.get('expert_locked_quotes', quotes)
    item['completed_grades'] = {
        'scout_ats': _grade_selection((picks.get('spread') or {}).get('side'),
            quotes.get('Spread'), away, home, spread=True),
        'scout_total': _grade_selection((picks.get('total') or {}).get('side'),
            quotes.get('Total'), away, home, spread=False),
        'expert_ats': _grade_selection(expert.get('ats_side'),
            expert_quotes.get('Spread'), away, home, spread=True),
        'expert_total': _grade_selection(expert.get('total_side'),
            expert_quotes.get('Total'), away, home, spread=False),
    }


def combined_cards(records, render_record, now):
    items = {}
    originals = {}
    from forecast_history import pregame_record
    for record in records:
        item = render_record(record)
        originals[record['scout']['game']['game_id']] = record['scout']
        item['locked_quotes'] = record['scout'].get('quotes', {})
        item['show_scores'] = True
        items[record['scout']['game']['game_id']] = item
        item['expert_locked_quotes'] = item['locked_quotes']
        item['locked_quotes'] = {}
        item['saved_picks'] = {'spread':{'side':None},'total':{'side':None}}
        item['show_scores'] = False
        item['forecast_pending'] = True
    for record in legacy_records():
        historical = instant(record['kickoff_utc']) <= now
        if record['game_id'] in items:
            historical = historical and instant(items[record['game_id']]['scout']['game']['kickoff_utc']) <= now
        if historical:
            try:
                pregame_record(record)
            except (KeyError, TypeError, ValueError):
                continue
        game = {key:record[key] for key in ('game_id','away_team','home_team','season','week','kickoff_utc')}
        total = record.get('totals')
        pick = record['components']['Blend']
        quotes = {'Spread':{'side_a':game['away_team'],'side_b':game['home_team'],
                            'line_a':record['quote']['line'],'line_b':-record['quote']['line']}}
        if total:quotes['Total']={'line_a':total['quote']['line']}
        selections = {'spread':{'side':pick['pick'],'label':'Pick'},
                      'total':{'side':total['prediction']['lean'] if total else None,'label':'Pick'}}
        archive_item = items.get(game['game_id'])
        approved = next((r for r in records if r['version']==record.get('_archive_version')),None)
        if approved:
            originals[game['game_id']] = approved['scout']
        else:
            originals.pop(game['game_id'],None)
        production_compatible = bool(approved)
        if instant(game['kickoff_utc']) > now:
            try:
                import hashlib
                from plug_publication import convert
                convert(record, hashlib.sha256((ROOT/'automatic_model.json').read_bytes()).hexdigest())
                production_compatible = True
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Keep historical cohorts intact; never relabel an incompatible seal.
        items[game['game_id']] = dict(scout={'game':game,'sources':[]},saved_picks=selections,
            locked_quotes=quotes,show_scores=False,prediction_margin=pick.get('away_margin'),
            expert_picks=None,expert_available=False,expert_access=False,assessment=None,
            url=url_for('fans.matchup',game_id=game['game_id']),
            legacy=True,production_compatible=production_compatible,ats_result=record.get('results',{}).get('Blend'))
        if approved:
            items[game['game_id']]['scout'] = approved['scout']
            items[game['game_id']]['show_scores'] = True
            # Only exact approved, sealed production forecasts may enter ATS selection.
            items[game['game_id']]['plug_ats_source'] = dict(
                model_version=record['version'], side=pick['pick'],
                edge=pick['ats_edge'], away_line=record['quote']['line'],
                source_sha256=record['_history_digest'],
                captured_at_utc=record['quote']['captured_at_utc'],
                sealed_at_utc=record['sealed_at_utc'])
        if archive_item:
            # Expert remains tied to its own report and quotes, independently of Scout.
            item = items[game['game_id']]
            for key in ('expert_picks','expert_available','expert_access','assessment','url'):
                item[key] = archive_item.get(key)
            item['expert_locked_quotes'] = archive_item['expert_locked_quotes']
            item['scout']['sources'] = archive_item['scout'].get('sources', [])
    upcoming, earlier = [], []
    wanted={game_id for game_id,item in items.items() if instant(item['scout']['game']['kickoff_utc'])>now}
    market_rows=[]
    path=ROOT/'public_money_snapshots.csv'
    if wanted and path.exists():
        with path.open(newline='',encoding='utf-8-sig') as source:
            market_rows=[r for r in csv.DictReader(source) if r.get('game_id') in wanted and r.get('market') in ('Moneyline','Spread','Total')]

    # Score records are imported or confirmed by the existing ESPN overlay.
    # An unconfirmed/live score must never be graded.
    completed = _completed_games(ROOT) if any(
        instant(item['scout']['game']['kickoff_utc']) <= now
        for item in items.values()) else {}
    for item in items.values():
        game = item['scout']['game']
        _attach_final(item, completed.get(game['game_id']))
        future = instant(game['kickoff_utc']) > now
        item['upcoming'] = future
        item['market'] = None
        item['line_movement'] = compare_line(originals[game['game_id']], ROOT, now, rows=market_rows) if future and game['game_id'] in originals else None
        if future:
            market = matchup_public_market(ROOT,dict(game_id=game['game_id'],away=game['away_team'],
                home=game['home_team'],kickoff_at=game['kickoff_utc']),now,rows=market_rows)
            item['market'] = [m for m in market['markets'] if m['key'] in ('Moneyline','Spread','Total') and m['sides']]
        (upcoming if future else earlier).append(item)
    upcoming.sort(key=lambda item:item['scout']['game']['kickoff_utc'])
    earlier.sort(key=lambda item:item['scout']['game']['kickoff_utc'],reverse=True)
    return upcoming, earlier


def load_schedule():
    from scout4.stats import read_csv
    from pregame_lines import effective_rows
    path = ROOT/'nfl_games.csv'
    return effective_rows(read_csv(path), path, include_scores=False)


def weekly_dashboard(records, render_record, now):
    """Join the authoritative current slate to immutable forecasts by game ID."""
    from site_week import active_slate
    from scout4.shadow import kickoff
    from scout4.stats import team_code
    import time
    rows = load_schedule()
    active, slate = active_slate(rows, now)
    future, earlier = combined_cards(records, render_record, now)
    by_id = {item['scout']['game']['game_id']:item for item in future+earlier}
    sections = {'games':[], 'underway_games':[], 'completed_games':[], 'awaiting_games':[],
                'historical_games':[], 'active_slate':active}
    current_ids = {row['game_id'] for row in slate}
    from fan_views import _score_cache
    live = (_score_cache['games'] if not _score_cache.get('stale') and
            time.monotonic() < _score_cache['expires'] else [])
    for row in slate:
        try:
            ko = kickoff(row)
        except (KeyError, ValueError, TypeError):
            continue
        game = {name:row[name] for name in ('game_id','season','week','away_team','home_team')}
        game['kickoff_utc'] = ko.isoformat()
        item = by_id.get(game['game_id'])
        if item is None or item.get('legacy') and ko > now and not item.get('production_compatible'):
            item = dict(scout={'game':game,'sources':[]}, saved_picks={}, locked_quotes={},
                show_scores=False, expert_available=False, expert_access=False,
                expert_picks=None, assessment=None, market=None, line_movement=None,
                pending=True, legacy=True, url=url_for('fans.matchup',game_id=game['game_id']))
        else:
            # Schedule identity wins; never attach a forecast to another kickoff.
            saved = item['scout']['game']
            if (saved['away_team'],saved['home_team'],instant(saved['kickoff_utc'])) != (
                    game['away_team'],game['home_team'],ko):
                item = dict(scout={'game':game,'sources':[]}, saved_picks={}, locked_quotes={},
                    show_scores=False, expert_available=False, expert_access=False,
                    expert_picks=None, assessment=None, market=None, line_movement=None,
                    pending=True, legacy=True, url=url_for('fans.matchup',game_id=game['game_id']))
            else:
                item['pending'] = bool(item.get('forecast_pending'))
        item['upcoming'] = ko > now
        observed = next((g for g in live if team_code(g.get('away')) == team_code(game['away_team'])
                        and team_code(g.get('home')) == team_code(game['home_team'])
                        and instant(g['date']) == ko), None)
        final = row.get('away_score') not in ('',None) and row.get('home_score') not in ('',None)
        if ko <= now and (final or observed and observed.get('state')=='post' and observed.get('completed') is True):
            sections['completed_games'].append(item)
        elif ko <= now and observed and observed.get('state')=='in':
            sections['underway_games'].append(item)
        elif ko > now:
            sections['games'].append(item)
        else:
            sections['awaiting_games'].append(item)
    sections['historical_games'] = [item for item in earlier if item['scout']['game']['game_id'] not in current_ids]
    for key in ('games','underway_games','completed_games','awaiting_games'):
        sections[key].sort(key=lambda item:instant(item['scout']['game']['kickoff_utc']))
    from plug_ats_select import decorate_dashboard
    return decorate_dashboard(sections, now)
