"""Public Scout policy: fade the approved points-only formula without rewriting source forecasts."""
import json
import math
from pathlib import Path

FORMULA_VERSION = "plug-points-only-4"
CONFIGURATION_SHA256 = "4b9a85b948cb0f1eeab19078df6d6f69a0244c947f460e01ab1537bbe9a12a31"
WEIGHTS = {"scout_scoring": 0.0, "plug_points_only": 1.0}
REPLAY_PATH = Path("data/scout4/fade_replay/2026_week6.json")


def replay_data(root):
    data = json.loads((Path(root) / REPLAY_PATH).read_text())
    if (data.get("season"), data.get("week"), data.get("formula_version"),
            data.get("configuration_sha256"), data.get("weights")) != (
            2026, 6, FORMULA_VERSION, CONFIGURATION_SHA256, WEIGHTS):
        raise ValueError("Week 6 Scout replay provenance does not match the approved formula")
    rows = data.get("games")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("Week 6 Scout replay must contain all 14 games")
    result = {}
    for row in rows:
        gid, pick = row.get("game_id"), row.get("scout_pick")
        if not isinstance(gid, str) or pick not in (row.get("away_team"), row.get("home_team")):
            raise ValueError("Invalid Week 6 Scout replay selection")
        if gid in result:
            raise ValueError("Duplicate Week 6 Scout replay game")
        result[gid] = row
    return result


def pick_for_record(record, root):
    """Return the public Scout side; archived original Blend picks are never changed."""
    season, week = int(record.get("season", 0)), int(record.get("week", 0))
    if season == 2026 and week == 6:
        replay = replay_data(root).get(record.get("game_id"))
        if not replay:
            return None
        if (replay["away_team"], replay["home_team"]) != (
                record.get("away_team"), record.get("home_team")):
            raise ValueError("Week 6 replay matchup identity differs from its source forecast")
        return replay["scout_pick"]
    if (record.get("version") != FORMULA_VERSION
            or record.get("configuration_sha256") != CONFIGURATION_SHA256
            or record.get("weights") != WEIGHTS):
        return None
    original = record.get("components", {}).get("Blend", {}).get("pick")
    if original == record.get("away_team"):
        return record.get("home_team")
    if original == record.get("home_team"):
        return record.get("away_team")
    return None


def grade_pick(record, game, pick):
    """Grade the faded side against the source forecast's frozen spread."""
    if pick is None:
        return "No Call"
    if not game or any(record.get(k) != game.get(k) for k in (
            "game_id", "away_team", "home_team")):
        return "Review needed"
    try:
        away, home = float(game.get("away_score")), float(game.get("home_score"))
        line = float(record["quote"]["line"])
        if not all(math.isfinite(v) for v in (away, home, line)):
            return "Pending"
    except (KeyError, TypeError, ValueError):
        return "Pending"
    if min(away, home) < 0 or not away.is_integer() or not home.is_integer():
        return "Review needed"
    away_edge = away - home + line
    edge = away_edge if pick == record["away_team"] else -away_edge
    return "Push" if abs(edge) < 1e-9 else "Win" if edge > 0 else "Loss"


def _tally(rows):
    counts = {key: sum(row["result"] == key for row in rows)
              for key in ("Win", "Loss", "Push", "Pending", "Review needed")}
    decisions = counts["Win"] + counts["Loss"]
    return dict(**counts, selected=len(rows), decisions=decisions,
                win_rate=round(100 * counts["Win"] / decisions, 1) if decisions else None)


def record_context(root, records, schedule, season, selected_week):
    """Build season and selected-week public records from immutable approved sources."""
    if season is None:
        return None
    games = {row.get("game_id"): row for row in schedule}
    rows = []
    for record in records:
        try:
            if int(record.get("season", 0)) != int(season) or int(record.get("week", 0)) < 6:
                continue
            pick = pick_for_record(record, root)
            if pick is None:
                continue
            game = games.get(record["game_id"])
            result = grade_pick(record, game, pick)
            line = float(record["quote"]["line"])
            signed_line = line if pick == record["away_team"] else -line
            rows.append(dict(
                game_id=record["game_id"], season=int(record["season"]),
                week=int(record["week"]), away_team=record["away_team"],
                home_team=record["home_team"], pick=pick,
                pick_line=f"{pick} {signed_line:+g}", result=result,
                kickoff_utc=record["kickoff_utc"],
                replayed=(int(record["week"]) == 6 and int(record["season"]) == 2026),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: (row["week"], row["kickoff_utc"], row["game_id"]))
    week_rows = [row for row in rows if row["week"] == int(selected_week)] if selected_week is not None else []
    return dict(
        formula_label="Fade of Original points-for/points-allowed",
        formula_version=FORMULA_VERSION,
        configuration_sha256=CONFIGURATION_SHA256,
        overall=_tally(rows), week=_tally(week_rows),
        selected_week=selected_week, rows=week_rows, season_rows=rows,
    )
