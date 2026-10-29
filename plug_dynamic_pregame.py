"""Pure, research-safe pregame Plug decisions from a VERIFIED current quote.

Does not read/write official receipts. The publication layer must independently
verify quote identity, timestamp, kickoff and persist append-only revisions.
"""
from datetime import datetime, timezone
import math

from plug_ats_v5_weekly import classify as classify_ats
from plug_totals_policy import select as select_total


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def decide(*, away_team, home_team, model_away_spread, market_away_spread,
           market_total, v14_total, original_total_side, quote_observed_utc,
           kickoff_utc, evaluation_utc):
    """Re-evaluate eligibility without modifying any frozen model projections.

    All times must be timezone-aware. A quote at/after kickoff or later than
    evaluation time is ineligible. No decision is issued after kickoff.
    """
    observed = _utc(quote_observed_utc)
    kickoff = _utc(kickoff_utc)
    evaluated = _utc(evaluation_utc)
    if not observed < kickoff or not evaluated < kickoff or observed > evaluated:
        raise ValueError("quote not verifiably available before kickoff")
    for value in (model_away_spread, market_away_spread, market_total, v14_total):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("non-finite model/market value")
    side = classify_ats(model_away_spread, market_away_spread, away_team, home_team)
    total = select_total(original_total_side, market_total, v14_total)
    # Totals below 48 or exactly matching market do not generate an independent
    # v14 signal. The fallback is retained for research, not auto-published.
    independent_total = total["source"] in ("follow_v14", "fade_v14")
    return {
        "ats_selected": side is not None,
        "ats_side": side,
        "ats_away_line": market_away_spread,
        "ou_selected": independent_total,
        "ou_side": total["side"] if independent_total else None,
        "ou_market_total": market_total,
        "ou_source": total["source"],
        "quote_observed_utc": observed.isoformat(),
        "evaluated_utc": evaluated.isoformat(),
        "kickoff_utc": kickoff.isoformat(),
    }
