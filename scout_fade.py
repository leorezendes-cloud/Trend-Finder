"""Public Scout policy: fade the approved points-only formula without rewriting source forecasts."""
import json
import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)

FORMULA_VERSION = "plug-points-only-4"
CONFIGURATION_SHA256 = "4b9a85b948cb0f1eeab19078df6d6f69a0244c947f460e01ab1537bbe9a12a31"
WEIGHTS = {"scout_scoring": 0.0, "plug_points_only": 1.0}
REPLAY_PATH = Path("scout_fade_replay_2026_week6.json")


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
        gid, original_pick = row.get("game_id"), row.get("scout_pick")
        away, home = row.get("away_team"), row.get("home_team")
        updated_pick = row.get("updated_formula_pick")
        if (not isinstance(gid, str) or away == home
                or original_pick not in (away, home) or updated_pick not in (away, home)
                or original_pick == updated_pick or row.get("expected_result") not in ("Win", "Loss")):
            raise ValueError("Invalid Week 6 Scout replay selection or inversion")
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
    season_number = int(season)
    week_number = int(selected_week) if selected_week is not None else None
    games = {row.get("game_id"): row for row in schedule}
    rows = []
    for record in records:
        try:
            record_season = int(record.get("season", 0))
            record_week = int(record.get("week", 0))
            if record_season != season_number or record_week < 6:
                continue
            # Week 6, 2026 is an independently approved replay cohort. Do not
            # let rejected/malformed legacy forecast files shadow that receipt.
            if season_number == 2026 and week_number == 6 and record_week == 6:
                continue
            pick = pick_for_record(record, root)
            if pick is None:
                continue
            game = games.get(record["game_id"])
            if int(record.get("season", 0)) == 2026 and int(record.get("week", 0)) == 6:
                replay = replay_data(root).get(record["game_id"])
                if (not replay or (replay["away_team"], replay["home_team"]) !=
                        (record.get("away_team"), record.get("home_team"))):
                    continue
                # The approved Week 6 fade replay carries the verified grading
                # for the inverted selection. Do not re-grade it with the original
                # Blend quote here: that quote's sign convention differs from the
                # replay's normalized away/home handicap.
                result = {"Win": "Loss", "Loss": "Win"}.get(replay["expected_result"], replay["expected_result"])
            else:
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
        except (OSError, KeyError, TypeError, ValueError):
            continue
    # Week 6 has a separately approved, immutable replay receipt. Do not
    # make its public W-L-P depend on the legacy forecast files still being
    # present in official_sources(): the replay itself contains all 14 picks
    # and their verified grades. Forecast records, when available, enrich the
    # display with the frozen spread; otherwise show the side without a line.
    if season_number == 2026 and week_number == 6:
        # The approved receipt is the source of truth for this cohort. Load it
        # once, without silently converting a bad/missing receipt into 0-0-0.
        replay_rows = replay_data(root)
        record_by_id = {r.get("game_id"): r for r in records}
        for gid, replay in replay_rows.items():
            pick = replay["scout_pick"]
            result = {"Win": "Loss", "Loss": "Win"}.get(
                replay["expected_result"], replay["expected_result"])
            record = record_by_id.get(gid)
            game = games.get(gid) or {}
            line = None
            if record:
                try:
                    line = float(record["quote"]["line"])
                    if not math.isfinite(line):
                        line = None
                except (KeyError, TypeError, ValueError):
                    line = None
            signed_line = (line if pick == replay["away_team"] else -line) if line is not None else None
            rows.append(dict(
                game_id=gid, season=2026, week=6,
                away_team=replay["away_team"], home_team=replay["home_team"],
                pick=pick,
                pick_line=f"{pick} {signed_line:+g}" if signed_line is not None else pick,
                result=result,
                kickoff_utc=(record or {}).get("kickoff_utc", game.get("gameday", "")),
                replayed=True,
            ))
    rows.sort(key=lambda row: (row["week"], row["kickoff_utc"], row["game_id"]))
    week_rows = [row for row in rows if row["week"] == week_number] if week_number is not None else rows
    return dict(
        formula_label="Fade of Original points-for/points-allowed",
        formula_version=FORMULA_VERSION,
        configuration_sha256=CONFIGURATION_SHA256,
        overall=_tally(rows), week=_tally(week_rows),
        selected_week=week_number, rows=week_rows, season_rows=rows,
    )


def safe_record_context(root, records, schedule, season, selected_week):
    """Keep public results pages available when optional Scout replay data is unavailable."""
    try:
        return record_context(root, records, schedule, season, selected_week)
    except (OSError, ValueError, TypeError, KeyError):
        logger.exception(
            "Scout fade record unavailable: root=%s season=%r selected_week=%r records=%s",
            root, season, selected_week,
            len(records) if hasattr(records, "__len__") else "unknown",
        )
        return None
