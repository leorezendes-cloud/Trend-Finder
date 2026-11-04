"""Small, pregame-only Scout evidence snapshot for Expert drafts.

Runs only during explicitly invoked draft generation; no network, paid calls,
storage writes, or background jobs. Never modifies the original Scout receipt.
"""
import csv
import json
from datetime import datetime, timezone
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




def _time(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Evidence timestamps require a timezone")
    return dt.astimezone(timezone.utc)


def _person_key(value):
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _personnel_context(scout, root, as_of):
    """Latest exact-game pregame depth/injury snapshot, plus recorded expected QBs.

    Editorial research may be newer than Scout's immutable forecast cutoff, but
    must be observed before this game kicks off and before the Expert decision.
    """
    game = scout.get("game", {})
    game_id = game.get("game_id")
    if not game_id:
        return {}, []
    try:
        kickoff = _time(game["kickoff_utc"])
    except (KeyError, TypeError, ValueError):
        return {}, []
    if as_of >= kickoff:
        return {}, []

    candidates = []
    folder = root / "data" / "scout4" / "personnel" / str(game.get("season"))
    for path in sorted(folder.glob("*/pregame_evidence.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            observed = _time(data.get("manifest", {}).get("retrieved_at"))
            if observed > as_of or observed >= kickoff:
                continue
            row = next((item for item in data.get("games", [])
                        if item.get("game_id") == game_id
                        and _time(item.get("kickoff_utc")) == kickoff), None)
            if row and _time(row.get("observed_at")) <= as_of:
                candidates.append((observed, data, row))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    if not candidates:
        return {}, []
    observed, data, row = max(candidates, key=lambda item: item[0])
    age_hours = max(0.0, (as_of - observed).total_seconds() / 3600)
    if age_hours > 24 * 7:
        return {}, []
    freshness = "current" if age_hours <= 24 else "stale"
    teams = {}
    sources = [{
        "name": "nflverse_personnel",
        "url": "https://github.com/nflverse/nflreadpy",
        "observed_at": observed.isoformat(),
        "description": "NFLverse depth-chart and weekly injury snapshot",
    }]

    # User-recorded expected starters are useful evidence, but remain explicitly
    # distinguished from independently verified or officially confirmed starters.
    reports = {}
    report_dir = root / "data" / "scout4" / "starter_reports"
    for path in sorted(report_dir.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            stamp = _time(report.get("observed_at"))
            if (report.get("game_id") == game_id and stamp <= as_of
                    and stamp < kickoff and report.get("team") in (game.get("away_team"), game.get("home_team"))):
                previous = reports.get(report["team"])
                if previous is None or stamp > previous[0]:
                    reports[report["team"]] = (stamp, report)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue

    for team in (game.get("away_team"), game.get("home_team")):
        personnel_data = row.get("personnel") or {}
        raw = personnel_data.get(team, {})
        raw = raw if isinstance(raw, dict) else {}
        injuries = raw.get("injury_rows", []) or []
        by_player = {}
        by_player_id = {}
        for injury in injuries:
            key = _person_key(injury.get("player_name") or injury.get("full_name")
                              or injury.get("display_name") or injury.get("name"))
            if key:
                by_player.setdefault(key, []).append(injury)
            player_id = injury.get("gsis_id") or injury.get("player_id")
            if player_id:
                by_player_id[str(player_id)] = injury

        def depth_rank(item):
            try:
                return int(item.get("pos_rank", 99))
            except (TypeError, ValueError):
                return 99

        depth = sorted(raw.get("qb_depth_order", []),
                       key=lambda item: (depth_rank(item), str(item.get("gsis_id", ""))))
        def qb_status(player):
            player_id = player.get("gsis_id")
            if player_id and str(player_id) in by_player_id:
                return by_player_id[str(player_id)]
            matches = by_player.get(_person_key(player.get("player_name")), [])
            return matches[0] if matches else {}
        def unavailable(status):
            return str(status or "").strip().lower() in {
                "out", "injured reserve", "reserve/injured", "ir", "pup",
                "physically unable to perform", "suspended", "inactive", "doubtful",
            }

        qb_rows = []
        for player in depth[:4]:
            injury = qb_status(player)
            qb_rows.append({
                "name": player.get("player_name"),
                "depth_rank": player.get("pos_rank"),
                "report_status": injury.get("report_status"),
                "practice_status": injury.get("practice_status"),
                "reported_injury": injury.get("report_primary_injury") or injury.get("report_secondary_injury"),
            })

        expected = None
        recorded = reports.get(team)
        if recorded:
            _, report = recorded
            match = next((player for player in depth
                          if player.get("gsis_id") == report.get("expected_qb_id")), None)
            source_url = report.get("source_url")
            if (match and not unavailable(qb_status(match).get("report_status"))
                    and isinstance(source_url, str) and source_url.startswith(("https://", "http://"))):
                injury = qb_status(match)
                expected = {
                    "name": match.get("player_name"), "depth_rank": match.get("pos_rank"),
                    "status": injury.get("report_status") or injury.get("practice_status"),
                    "basis": "operator-recorded expected starter; source not independently verified",
                }
                source_name = "expected_qb_report_" + team
                sources.append({
                    "name": source_name, "url": source_url,
                    "observed_at": _time(report["observed_at"]).isoformat(),
                    "description": report.get("source_evidence", "")[:500],
                })
        if expected is None:
            available = [player for player in depth
                         if not unavailable(qb_status(player).get("report_status"))]
            if available:
                player = available[0]
                injury = qb_status(player)
                expected = {
                    "name": player.get("player_name"), "depth_rank": player.get("pos_rank"),
                    "status": injury.get("report_status") or injury.get("practice_status"),
                    "basis": ("next listed quarterback after higher depth-chart options were marked unavailable"
                              if depth_rank(player) > 1
                              else "depth-chart QB1; expected, not officially confirmed"),
                }

        key_injuries = []
        for injury in injuries:
            name = injury.get("player_name") or injury.get("full_name") or injury.get("display_name") or injury.get("name")
            position = injury.get("position") or injury.get("pos_abb")
            report_status = injury.get("report_status")
            practice_status = injury.get("practice_status")
            if not any((name, report_status, practice_status,
                        injury.get("report_primary_injury"), injury.get("practice_primary_injury"))):
                continue
            key_injuries.append({
                "player": name, "position": position,
                "report_status": report_status, "practice_status": practice_status,
                "reported_injury": injury.get("report_primary_injury") or injury.get("report_secondary_injury"),
                "practice_injury": injury.get("practice_primary_injury") or injury.get("practice_secondary_injury"),
            })
        key_injuries.sort(key=lambda item: (
            0 if str(item.get("position", "")).upper() == "QB" else 1,
            0 if str(item.get("report_status", "")).lower() in ("out", "doubtful") else 1,
            str(item.get("player") or "")))
        teams[team] = {
            "expected_quarterback": expected,
            "quarterback_depth_chart": qb_rows,
            "key_injuries": key_injuries[:12],
            "injury_coverage": ("reported rows only; no listed injury does not establish health"
                               if injuries else "unknown; no injury rows supplied"),
            "depth_chart_updated_at": raw.get("depth_updated_at"),
            "depth_chart_stale": raw.get("depth_stale"),
            "snapshot_observed_at": observed.isoformat(),
            "snapshot_freshness": freshness,
        }
    return {
        "observed_at": observed.isoformat(),
        "age_hours": round(age_hours, 1),
        "freshness": freshness,
        "source": data.get("manifest", {}).get("source", "NFLverse"),
        "teams": teams,
    }, sources


def _weather_context(scout, root, as_of):
    """Latest exact-game weather forecast observed before kickoff and Expert review."""
    game = scout.get("game", {})
    game_id = game.get("game_id")
    if not game_id:
        return {}, []
    try:
        kickoff = _time(game["kickoff_utc"])
    except (KeyError, TypeError, ValueError):
        return {}, []
    candidates = []
    for path in sorted((root / "data" / "scout4" / "weather").glob("*/evidence.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("records", []):
                if row.get("game_id") != game_id or _time(row.get("kickoff_utc")) != kickoff:
                    continue
                observed = _time(row.get("observed_at"))
                if observed <= as_of and observed < kickoff:
                    candidates.append((observed, row))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
    if not candidates:
        return {}, []
    observed, row = max(candidates, key=lambda item: item[0])
    age_hours = max(0.0, (as_of - observed).total_seconds() / 3600)
    if age_hours > 24 * 7:
        return {}, []
    weather = {
        "observed_at": observed.isoformat(),
        "age_hours": round(age_hours, 1),
        "freshness": "current" if age_hours <= 24 else "stale",
        "source": row.get("source", "Open-Meteo live forecast"),
        "stadium": row.get("stadium"),
        "roof_context": row.get("roof_context"),
        "hours": [{
            "valid_at_utc": hour.get("valid_at_utc"),
            "temperature_f": hour.get("temperature_2m"),
            "wind_mph": hour.get("wind_speed_10m"),
            "wind_gusts_mph": hour.get("wind_gusts_10m"),
            "precipitation_inches": hour.get("precipitation"),
            "precipitation_probability_pct": hour.get("precipitation_probability"),
        } for hour in (row.get("hours") or [])[:4]],
        "limitations": row.get("limitations", []),
    }
    source_url = row.get("request_url") or row.get("roof_source")
    sources = ([{
        "name": "open_meteo_weather",
        "url": source_url,
        "observed_at": observed.isoformat(),
        "description": "Pregame stadium-area weather forecast; roof/exposure caveats retained",
    }] if isinstance(source_url, str) and source_url.startswith(("https://", "http://")) else [])
    return weather, sources


def _attach_personnel(output, scout, root, as_of):
    personnel, personnel_sources = _personnel_context(scout, root, as_of)
    weather, weather_sources = _weather_context(scout, root, as_of)
    if personnel:
        output["personnel"] = personnel
    if weather:
        output["weather"] = weather
    sources = personnel_sources + weather_sources
    if sources:
        output["sources"] = sources
    output["expert_as_of_utc"] = as_of.isoformat()
    return output


def snapshot(scout, root=None, as_of=None):
    """Bounded, verifiable team form and box-score standouts before kickoff.

    Same-day games are excluded because a date alone cannot establish whether
    their result was public at the forecast cutoff. Missing cache -> no claims.
    """
    root = Path(root or Path(__file__).resolve().parent)
    game = scout.get("game", {})
    try:
        season = int(game["season"])
        cutoff = datetime.fromisoformat(scout["cutoff_utc"].replace("Z", "+00:00")).date().isoformat()
        decision_time = as_of or scout["cutoff_utc"]
        if isinstance(decision_time, datetime):
            decision_time = decision_time.astimezone(timezone.utc)
        else:
            decision_time = _time(decision_time)
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
        return _attach_personnel(output, scout, root, decision_time)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        player_path = _feed_path(root, season, manifest, "player")
        if not player_path:
            return _attach_personnel(output, scout, root, decision_time)
        player_rows = _rows(player_path)
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError, csv.Error):
        return _attach_personnel(output, scout, root, decision_time)
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
    # Keep the historical form snapshot bounded; personnel is separately capped.
    if len(json.dumps(output)) > 2300:
        output.pop("player_performances", None)
        output.pop("player_source", None)
    return _attach_personnel(output, scout, root, decision_time)
