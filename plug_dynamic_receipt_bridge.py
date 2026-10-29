"""Research-only bridge from immutable, validated model receipts.

Never recomputes models, changes official picks or publishes this journal.
Both sources must exist and match the exact game and kickoff.
"""
from plug_dynamic_errors import Unavailable, WeeklyReceiptPending
from datetime import datetime, timezone
from pathlib import Path

from plug_ats_v5_weekly import read_week as read_ats_week
from plug_ou_receipts import read as read_ou
from plug_dynamic_research import observe


def _utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    return stamp.astimezone(timezone.utc)


def observe_from_receipts(root, *, game_id, evaluation_utc, live=False):
    """Opt-in per-game refresh using previously issued independent predictions."""
    parts = game_id.split("_")
    if len(parts) != 4 or not all(part.isalnum() for part in parts):
        raise ValueError("Invalid game identity")
    year, week = int(parts[0]), int(parts[1])
    now = _utc(evaluation_utc)
    ats = read_ats_week(year, week)
    if ats is None:
        raise WeeklyReceiptPending("Verified ATS v5 weekly receipt unavailable")
    rows = [row for row in ats["games"] if row["game_id"] == game_id]
    if len(rows) != 1:
        raise Unavailable("Game absent from verified ATS slate")
    row = rows[0]
    ou = read_ou(root, game_id, verify_source=True)
    if ou is None:
        raise Unavailable("Verified O/U v14 receipt unavailable")
    if (row["away_team"] != parts[2] or row["home_team"] != parts[3]
            or ou["away_team"] != parts[2] or ou["home_team"] != parts[3]
            or _utc(row["kickoff_utc"]) != _utc(ou["kickoff_utc"])
            or _utc(row["kickoff_utc"]) <= now
            or _utc(ou["issued_at_utc"]) > now
            or _utc(ats["issued_at_utc"]) > now):
        raise ValueError("Receipt identities or pregame timing disagree")
    decision = observe(Path(root), game_id=game_id, away_team=parts[2],
                   home_team=parts[3], kickoff_utc=row["kickoff_utc"],
                   model_away_spread=row["model_away_spread"],
                   v14_total=ou["v14_total"],
                   original_total_side=ou["original_scout_side"],
                   evaluation_utc=now.isoformat(),
                   **({"clock":lambda:datetime.now(timezone.utc)} if live else {}))

    from plug_dynamic_official import enroll
    enroll(root, game_id, decision,
           datetime.now(timezone.utc).isoformat() if live else now.isoformat())
    return decision
