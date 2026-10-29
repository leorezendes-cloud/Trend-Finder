"""Grade only verified immutable dynamic closing receipts, never current odds.

Research grading remains separate from official historical standings.
"""
import math
from plug_dynamic_closing import read_closing


def grade_closing(root, game_id, *, away_score, home_score):
    receipt = read_closing(root, game_id)
    if receipt is None:
        return {"status": "unavailable", "ats": None, "ou": None}
    scores = (away_score, home_score)
    try:
        away, home = (float(v) for v in scores)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid final score") from error
    if not all(math.isfinite(v) and v >= 0 and v.is_integer() for v in (away, home)):
        raise ValueError("Invalid final score")
    away_team, home_team = game_id.split("_")[-2:]
    ats = ou = None
    if receipt["ats_selected"]:
        side = receipt["ats_side"]
        if side not in (away_team, home_team):
            raise ValueError("Closing receipt ATS identity mismatch")
        margin = away - home + float(receipt["ats_away_line"])
        if not math.isfinite(margin):
            raise ValueError("Invalid closing spread")
        ats = "Push" if abs(margin) < 1e-9 else (
            "Win" if (margin > 0) == (side == away_team) else "Loss")
    if receipt["ou_selected"]:
        side = receipt["ou_side"]
        if side not in ("Over", "Under"):
            raise ValueError("Invalid closing total selection")
        margin = away + home - float(receipt["ou_market_total"])
        if not math.isfinite(margin):
            raise ValueError("Invalid closing total")
        ou = "Push" if abs(margin) < 1e-9 else (
            "Win" if (margin > 0) == (side == "Over") else "Loss")
    return {"status": "locked", "ats": ats, "ou": ou,
            "revision": receipt["revision"],
            "receipt_sha256": receipt["receipt_sha256"]}
