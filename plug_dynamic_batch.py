"""Opt-in batch refresh for dynamic Plug research; never publishes official picks."""
from plug_dynamic_errors import Unavailable, WeeklyReceiptPending
import csv
from datetime import datetime, timezone
from pathlib import Path

from scheduled_ats_capture import upcoming_games
from plug_dynamic_receipt_bridge import observe_from_receipts


def refresh(root, *, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    game_ids = sorted(set(upcoming_games(root, now)))
    from site_week import active_slate
    schedule_path = root/'nfl_games.csv'
    active = None
    if schedule_path.is_file():
        with schedule_path.open(newline='',encoding='utf-8-sig') as stream:
            active, _ = active_slate(list(csv.DictReader(stream)),now)
    result = {"eligible": len(game_ids), "refreshed": 0, "unavailable": 0,
              "failed": 0, "reasons": {}, "games": {},
              "awaiting_next_week": 0, "next_week_games": {}}
    for game_id in game_ids:
        try:
            observe_from_receipts(root, game_id=game_id, evaluation_utc=now.isoformat(), live=True)
            result["refreshed"] += 1
        except Unavailable as exc:
            # A missing frozen source or stale quote cannot become a pick.
            parts = game_id.split('_')
            # An eight-day market window can see next Thursday before the
            # current week is finished. Only the expected absence of a future
            # REG weekly receipt is informational; no evidence check is relaxed.
            future_week = (active is not None and active[1] == 'REG'
                           and (int(parts[0]),int(parts[1])) > (active[0],active[2]))
            if isinstance(exc,WeeklyReceiptPending) and future_week:
                result['awaiting_next_week'] += 1
                result['next_week_games'][game_id] = (
                    'Awaiting the complete upcoming-week ATS v5 receipt; '
                    'the automatic issuer retries every five minutes.')
                continue
            result["unavailable"] += 1
            result["games"][game_id] = str(exc)
            name = type(exc).__name__
            result["reasons"][name] = result["reasons"].get(name, 0) + 1
        except Exception:
            # Unexpected programming faults should be visible to the scheduler.
            result["failed"] += 1
            raise
    # Keep missing validated sources visible as nonfatal, but never imply
    # refresh success when none of the eligible games could be evaluated.
    result["state"] = ("idle" if not game_ids else
                       "ok" if result["refreshed"] and not result["unavailable"] else
                       "waiting_next_week" if result["awaiting_next_week"] == len(game_ids) else
                       "partial" if result["refreshed"] else "unavailable")
    return result
