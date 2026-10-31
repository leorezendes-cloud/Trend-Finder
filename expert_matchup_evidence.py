"""Small, pregame-only Scout evidence snapshot for Expert drafts.

Runs only during explicitly invoked draft generation; no network, paid calls,
storage writes, or background jobs. Never modifies the original Scout receipt.
"""
import csv
import json
from datetime import datetime
from pathlib import Path


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _number(value):
    try:
        n = float(value)
        return n if n == n and abs(n) < 100000 else None
    except (TypeError, ValueError):
        return None


def _feed_path(root, season, manifest, kind):
    cache = (root / "data" / "scout4").resolve()
    relative = manifest.get("files", {}).get(kind, {}).get("path")
    if not isinstance(relative, str):
        return None
    path = (cache / relative).resolve()
    return path if path.is_relative_to(cache) and path.is_file() else None


def snapshot(scout, root=None):
    """Bounded, verifiable team form and box-score standouts before kickoff.

    Same-day games are excluded because a date alone cannot establish whether
    their result was public at the forecast cutoff. Missing cache -> no claims.
    """
    root = Path(root or Path(__file__).resolve().parent)
    game = scout.get("game", {})
    try:
        season = int(game["season"])
        cutoff = datetime.fromisoformat(scout["cutoff_utc"].replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError, KeyError, AttributeError):
        return {}
    away, home = game.get("away_team"), game.get("home_team")
    if not away or not home or away == home:
        return {}
    schedule_path = root / "nfl_games.csv"
    if not schedule_path.is_file():
        return {}
    manifest_path = root / "data" / "scout4" / str(season) / "latest.json"
    try:
        schedule = _rows(schedule_path)
    except (OSError, UnicodeError, csv.Error):
        return {}
    history = []
    for row in schedule:
        if (str(row.get("season")) != str(season) or row.get("game_type") != "REG"
                or not row.get("gameday") or row["gameday"] >= cutoff):
            continue
        a, h = _number(row.get("away_score")), _number(row.get("home_score"))
        if a is None or h is None:
            continue
        history.append((row, a, h))
    teams = []
    eligible_ids = set()
    for team in (away, home):
        recent = [(g, a, h) for g, a, h in history
                  if team in (g.get("away_team"), g.get("home_team"))]
        recent.sort(key=lambda item: (item[0]["gameday"], item[0].get("game_id", "")), reverse=True)
        recent = recent[:3]
        games = []
        for g, a, h in recent:
            is_away = team == g["away_team"]
            own, opp = (a, h) if is_away else (h, a)
            games.append(dict(date=g["gameday"],
                              opponent=g["home_team"] if is_away else g["away_team"],
                              score=f"{int(own)}-{int(opp)}",
                              outcome="W" if own > opp else "L" if own < opp else "T"))
            eligible_ids.add(g["game_id"])
        if games:
            teams.append(dict(team=team, recent=games,
                              recent_record=f"{sum(g['outcome']=='W' for g in games)}-"
                                            f"{sum(g['outcome']=='L' for g in games)}"
                                            f"{'-'+str(sum(g['outcome']=='T' for g in games)) if any(g['outcome']=='T' for g in games) else ''}"))
    output = dict(source="Saved NFL schedule/final scores (pregame cutoff)",
                  cutoff_date_exclusive=cutoff, team_form=teams)
    if not manifest_path.is_file() or not eligible_ids:
        return output
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        player_path = _feed_path(root, season, manifest, "player")
        if not player_path:
            return output
        player_rows = _rows(player_path)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError, csv.Error):
        return output
    standouts = []
    for p in player_rows:
        if (p.get("game_id") not in eligible_ids
                or str(p.get("season")) != str(season)
                or p.get("season_type") != "REG"
                or p.get("team") not in (away, home)
                or not p.get("player_id")):
            continue
        name = p.get("player_display_name") or p.get("player_name")
        if not name:
            continue
        options = (("passing_yards", "passing yards", 180),
                   ("receiving_yards", "receiving yards", 65),
                   ("rushing_yards", "rushing yards", 65),
                   ("def_sacks", "sacks", 2))
        for field, label, threshold in options:
            value = _number(p.get(field))
            if value is not None and value >= threshold:
                match = next((g for g, _, _ in history if g["game_id"] == p["game_id"]), None)
                if match is not None:
                    standouts.append((match["gameday"], value / threshold,
                                     dict(player=name[:65], team=p["team"], date=match["gameday"],
                                          metric=label, value=int(value) if value.is_integer() else round(value, 1))))
    standouts.sort(key=lambda x: (x[0], x[1]), reverse=True)
    seen = set()
    best = []
    for _, _, item in standouts:
        key = (item["player"], item["team"], item["date"])
        if key in seen:
            continue
        seen.add(key)
        best.append(item)
        if len(best) == 3:
            break
    if best:
        output["player_performances"] = best
        output["player_source"] = "Cached Scout 4.0 player box-score feed; observed games, not starter verification or projections"
    # Hard cap for API token cost. Keep the bounded snapshot factual.
    if len(json.dumps(output)) > 2300:
        output.pop("player_performances", None)
        output.pop("player_source", None)
    return output
