"""Clearly labeled retrospective Plug v5/v14 simulations for 2026 Weeks 6-7.

These are research replays, not pregame-issued picks or official receipts.
They are kept outside the immutable prospective receipt stores.
"""
import csv
import math
from pathlib import Path


def historical_simulations(root, season, week):
    if int(season) != 2026 or int(week) not in (6, 7):
        return []
    root = Path(root)
    schedule_path = root / "nfl_games.csv"
    with schedule_path.open(newline="", encoding="utf-8-sig") as stream:
        games = [r for r in csv.DictReader(stream)
                 if r.get("game_type") == "REG"
                 and int(r.get("season") or 0) == int(season)
                 and int(r.get("week") or 0) == int(week)]
    if not games:
        return []

    from plug_ats_v5_model import projections as ats_projections
    from plug_ats_v5_weekly import classify
    from plug_v14_model import projections as total_projections
    from plug_totals_policy import select as select_total
    from forecast_history import official_sources

    ids = {g["game_id"] for g in games}
    ats = ats_projections(schedule_path, int(season), int(week))
    totals = total_projections(schedule_path, season=int(season), eligible_ids=ids)
    forecasts = official_sources(root)
    output = []
    for game in games:
        gid = game["game_id"]
        try:
            away_score = float(game["away_score"])
            home_score = float(game["home_score"])
            if (not math.isfinite(away_score) or not math.isfinite(home_score)
                    or not away_score.is_integer() or not home_score.is_integer()):
                continue
        except (KeyError, TypeError, ValueError):
            continue

        source = forecasts.get(gid) or {}
        # ATS and O/U are independent systems. A missing source for one market
        # must not silently erase a valid selection in the other.
        spread = projection = None
        ats_side = ats_result = ats_pick = None
        try:
            # Use the frozen pregame spread, never a later closing/current line.
            spread = float(source["quote"]["line"])
            projection = float(ats[gid])
            if not math.isfinite(spread) or not math.isfinite(projection):
                raise ValueError("Invalid ATS source")
            ats_side = classify(projection, spread, game["away_team"], game["home_team"])
            if ats_side:
                edge = away_score - home_score + spread
                ats_result = "Push" if abs(edge) < 1e-9 else (
                    "Win" if (edge > 0) == (ats_side == game["away_team"]) else "Loss")
                signed_line = spread if ats_side == game["away_team"] else -spread
                ats_pick = f"{ats_side} {signed_line:+g}"
        except (KeyError, TypeError, ValueError):
            pass

        total_line = v14 = ou_side = ou_result = ou_pick = None
        try:
            # O/U v14 uses its own frozen pregame total and saved original lean.
            total_line = float(source["totals"]["quote"]["line"])
            v14 = float(totals[gid])
            original = ((source.get("totals") or {}).get("prediction") or {}).get("lean")
            if (not math.isfinite(total_line) or not math.isfinite(v14)
                    or not 10 < total_line < 90
                    or original not in ("Over", "Under")):
                raise ValueError("Missing or invalid O/U source")
            decision = select_total(original, total_line, v14)
            ou_side = decision["side"]
            total_actual = away_score + home_score
            delta = total_actual - total_line
            ou_result = "Push" if abs(delta) < 1e-9 else (
                "Win" if (delta > 0) == (ou_side == "Over") else "Loss")
            ou_pick = f"{ou_side} {total_line:g}"
        except (KeyError, TypeError, ValueError):
            pass

        if not ats_side and not ou_side:
            continue
        output.append({
            "game_id": gid, "season": int(season), "week": int(week),
            "away_team": game["away_team"], "home_team": game["home_team"],
            "ats_side": ats_side, "ats_pick": ats_pick, "ats_result": ats_result,
            "ou_side": ou_side, "ou_pick": ou_pick, "ou_result": ou_result,
            "ats_projection": projection, "v14_projection": v14,
            "spread_line": spread, "total_line": total_line,
            "source": "Historical simulation · not issued pregame",
        })
    return output
