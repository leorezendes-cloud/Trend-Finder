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
            source = forecasts.get(gid) or {}
            # Use the actual frozen pregame sportsbook quotes from the saved
            # forecast, never a later closing/current line from the schedule.
            spread = float(source["quote"]["line"])
            total_line = float(source["totals"]["quote"]["line"])
            projection = float(ats[gid])
            v14 = float(totals[gid])
            if not all(math.isfinite(v) for v in
                       (away_score, home_score, spread, total_line, projection, v14)):
                continue
            if (not away_score.is_integer() or not home_score.is_integer()
                    or not 10 < total_line < 90):
                continue
        except (KeyError, TypeError, ValueError):
            continue

        # v5 selection uses its exact production classifier and schedule spread.
        side = classify(projection, spread, game["away_team"], game["home_team"])
        ats_result = None
        ats_pick = None
        if side:
            edge = away_score - home_score + spread
            ats_result = "Push" if abs(edge) < 1e-9 else (
                "Win" if (edge > 0) == (side == game["away_team"]) else "Loss")
            signed_line = spread if side == game["away_team"] else -spread
            ats_pick = f"{side} {signed_line:+g}"

        # Below 48, v14 policy deliberately retains the original Scout lean.
        # Require the saved pregame Scout direction; never infer it from the final.
        original = ((source.get("totals") or {}).get("prediction") or {}).get("lean")
        if original not in ("Over", "Under"):
            continue
        decision = select_total(original, total_line, v14)
        ou_side = decision["side"]
        total_actual = away_score + home_score
        delta = total_actual - total_line
        ou_result = "Push" if abs(delta) < 1e-9 else (
            "Win" if (delta > 0) == (ou_side == "Over") else "Loss")
        output.append({
            "game_id": gid, "season": int(season), "week": int(week),
            "away_team": game["away_team"], "home_team": game["home_team"],
            "ats_side": side, "ats_pick": ats_pick, "ats_result": ats_result,
            "ou_side": ou_side, "ou_pick": f"{ou_side} {total_line:g}",
            "ou_result": ou_result, "ats_projection": projection,
            "v14_projection": v14, "spread_line": spread, "total_line": total_line,
            "source": "Historical simulation · not issued pregame",
        })
    return output
