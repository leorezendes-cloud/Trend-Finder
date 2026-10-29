"""Opt-in batch refresh for dynamic Plug research; never publishes official picks."""
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
    result = {"eligible": len(game_ids), "refreshed": 0, "unavailable": 0,
              "failed": 0, "reasons": {}}
    for game_id in game_ids:
        try:
            observe_from_receipts(root, game_id=game_id, evaluation_utc=now.isoformat())
            result["refreshed"] += 1
        except (ValueError, KeyError, OSError, TypeError) as exc:
            # A missing frozen source or stale quote cannot become a pick.
            result["unavailable"] += 1
            name = type(exc).__name__
            result["reasons"][name] = result["reasons"].get(name, 0) + 1
        except Exception:
            # Unexpected programming faults should be visible to the scheduler.
            result["failed"] += 1
            raise
    return result
