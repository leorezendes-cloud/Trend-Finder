"""Read-only owner comparison of existing, issued NFL predictions.

No requests, model inference, extra storage, or writes. Scout is counted once;
the recovered original and QB variant are one model family.
"""
import os
from collections import Counter
from datetime import datetime, timezone


def _safe_scout(root, game, now):
    try:
        from scout_dynamic_public import state
        value = state(root, game, now=now)
        if value and value['status'] in ('pregame', 'locked'):
            return value['row'], value['status']
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None, None


def _safe_plug(root, game, now):
    if os.environ.get('TREND_FINDAH_DYNAMIC_OFFICIAL') != '1':
        return None, None
    try:
        from plug_dynamic_official import official_state
        value = official_state(root, game['game_id'], as_of_utc=now.isoformat())
        if value and value['kickoff_utc'] == game['kickoff_utc']:
            return value, 'locked' if now >= datetime.fromisoformat(
                game['kickoff_utc'].replace('Z', '+00:00')) else 'pregame'
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None, None


def compare(rows, root, now=None):
    """Show current verified selections and conservative forward consensus results."""
    now = now or datetime.now(timezone.utc)
    items = []
    results = Counter()
    for r in rows:
        if r.get('season') != '2026':
            continue
        game = dict(game_id=r['game_id'], away_team=r['away'],
                    home_team=r['home'], kickoff_utc=r.get('kickoff_utc'))
        if not game['kickoff_utc']:
            continue
        scout, scout_state = _safe_scout(root, game, now)
        plug, plug_state = _safe_plug(root, game, now)
        recovered = None
        family = None
        if r.get('locked') and r.get('qb_record'):
            recovered = r['qb_record'].get('pick')
            family = 'QB edition'
        elif r.get('locked') and r.get('state') == 'ready':
            recovered = r['result']['selection'].get('pick')
            family = 'Original'
        # A preview is not an issued independent selection.
        recovered = recovered if recovered in ('Over', 'Under') else None
        scout_ou = scout.get('ou_side') if scout else None
        scout_ats = scout.get('ats_side') if scout else None
        plug_ou = plug.get('ou_side') if plug and plug.get('ou_selected') else None
        plug_ats = plug.get('ats_side') if plug and plug.get('ats_selected') else None
        ou = [v for v in (recovered, scout_ou, plug_ou) if v in ('Over', 'Under')]
        ats = [v for v in (scout_ats, plug_ats) if v in (r['away'], r['home'])]
        ou_label = ('3/3 agree' if len(ou) == 3 and len(set(ou)) == 1 else
                    'Split' if len(ou) >= 2 and len(set(ou)) > 1 else
                    'Partial' if ou else 'Awaiting picks')
        ats_label = ('Scout + Plug agree' if len(ats) == 2 and len(set(ats)) == 1 else
                     'Scout / Plug split' if len(ats) == 2 else 'No independent ATS feed')
        # Grade only fully locked three-way agreement, at the original recovered
        # pregame line; never mistake an active projection for a historical pick.
        if (ou_label == '3/3 agree' and r.get('locked') and
                scout_state == plug_state == 'locked'):
            from recovered_nfl_tracker import grade
            actual = r.get('actual_total')
            market = r['result']['market_total']
            outcome = grade(recovered, market, actual)
            if outcome in ('Win', 'Loss', 'Push'):
                results[outcome] += 1
            elif outcome == 'Pending':
                results['Pending'] += 1
        items.append(dict(game_id=r['game_id'], away=r['away'], home=r['home'],
            kickoff=r['kickoff_utc'], recovered=recovered, family=family,
            scout_ou=scout_ou, plug_ou=plug_ou, scout_ats=scout_ats,
            plug_ats=plug_ats, ou_agreement=ou_label, ats_agreement=ats_label,
            scout_state=scout_state, plug_state=plug_state))
    return dict(rows=items, record=results, updated=now.isoformat())
