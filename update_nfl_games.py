#!/usr/bin/env python3
"""Safely refresh completed NFL scores in the project's existing nfl_games.csv.

Usage:
    python3 update_nfl_games.py           # read-only preview (default)
    python3 update_nfl_games.py --apply   # backup and atomically write verified finals
    python3 update_nfl_games.py --season 2025 --apply

Requirements: nflreadpy (already used by Scout), internet access.

Only an ESPN-confirmed final with matching scores from nflreadpy can be written.
Existing nonblank spreads are never changed. Never fabricates betting splits.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parent
CSV_FILE = PROJECT / "nfl_games.csv"
STATUS_FILE = PROJECT / "nfl_games_update_status.json"
BACKUPS = PROJECT / "backups"

TEAM_ALIASES = {
    "WSH": "WAS", "JAC": "JAX", "LAR": "LA", "STL": "LA",
    "OAK": "LV", "SD": "LAC", "SDG": "LAC",
}
PLAYOFF_WEEK = {"WC": 1, "DIV": 2, "CON": 3, "SB": 4}


def as_int(value):
    if value is None or str(value).strip() == "":
        return None
    n = float(value)
    if not n.is_integer() or n < 0:
        raise ValueError(f"Invalid nonnegative whole-number score: {value!r}")
    return int(n)


def fmt(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def normalize(team):
    code = str(team or "").upper()
    return TEAM_ALIASES.get(code, code)


def event_key(game):
    return (normalize(game.get("away_team")), normalize(game.get("home_team")))


def week_key(game):
    stage = str(game.get("game_type", "REG")).upper()
    if stage == "REG":
        return (2, int(game["week"]))
    if stage in PLAYOFF_WEEK:
        return (3, PLAYOFF_WEEK[stage])
    return None  # Ignore preseason/unknown stages for this first updater.


def fetch_espn_finals(season, season_type, week):
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        f"?season={season}&seasontype={season_type}&week={week}&limit=50"
    )
    req = Request(url, headers={"User-Agent": "TrendFindah3000/1.0"})
    with urlopen(req, timeout=25) as response:
        payload = json.load(response)
    finals = {}
    for event in payload.get("events", []):
        if event.get("status", {}).get("type", {}).get("completed") is not True:
            continue
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        opponents = {}
        for entry in competitions[0].get("competitors", []):
            side = entry.get("homeAway")
            if side not in ("home", "away"):
                continue
            opponents[side] = (normalize(entry.get("team", {}).get("abbreviation")), as_int(entry.get("score")))
        if "home" in opponents and "away" in opponents:
            away, home = opponents["away"], opponents["home"]
            finals[(away[0], home[0])] = (away[1], home[1])
    return finals


def load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        rows = list(reader)
    if not headers or "game_id" not in headers or "spread_line" not in headers:
        raise ValueError("Unexpected nfl_games.csv structure: missing game_id or spread_line.")
    duplicate_ids = [k for k, n in Counter(x["game_id"] for x in rows).items() if n > 1]
    if duplicate_ids:
        raise ValueError(f"CSV contains duplicate game IDs: {duplicate_ids[:5]}")
    return headers, rows


def load_schedule(season):
    import nflreadpy as nfl  # Keep optional dependency out of CSV-only tests.
    return nfl.load_schedules(season).to_dicts()


def prepare_changes(rows, headers, schedule, season, fetch_finals=fetch_espn_finals):
    """Mutates copies of rows; returns updated rows, metrics and warnings."""
    updated = [dict(x) for x in rows]
    positions = {row["game_id"]: i for i, row in enumerate(updated)}
    source_games = {}
    for item in schedule:
        if str(item.get("season")) != str(season):
            continue
        game_id = fmt(item.get("game_id"))
        if not game_id:
            continue
        if game_id in source_games:
            raise ValueError(f"Duplicate game_id in source schedule: {game_id}")
        source_games[game_id] = item

    # First collect candidate weeks. Don't hit ESPN for future/unscored games.
    candidates = []
    for game_id, source in source_games.items():
        key = week_key(source)
        if key is None:
            continue
        away = as_int(source.get("away_score"))
        home = as_int(source.get("home_score"))
        if away is None or home is None:
            continue
        current = updated[positions[game_id]] if game_id in positions else None
        if current and current.get("away_score") != "" and current.get("home_score") != "" and current.get("result") != "":
            continue  # Never overwrite an already scored local game.
        candidates.append((game_id, source, key, away, home))

    confirmations = {}
    for stage, week in sorted(set(x[2] for x in candidates)):
        # If any remote fetch fails, raise without modifying the CSV.
        confirmations[(stage, week)] = fetch_finals(season, stage, week)

    metrics = {"source_games": len(source_games), "candidates": len(candidates),
               "new_finals": 0, "filled_finals": 0, "skipped_unconfirmed": 0,
               "skipped_score_mismatch": 0, "skipped_identity_mismatch": 0,
               "without_spread": 0}
    warnings = []
    for game_id, source, stage_week, away, home in candidates:
        actual = confirmations[stage_week].get(event_key(source))
        if actual is None:
            metrics["skipped_unconfirmed"] += 1
            continue
        if actual != (away, home):
            metrics["skipped_score_mismatch"] += 1
            warnings.append(f"{game_id}: nflreadpy scores {(away, home)} disagree with ESPN {actual}; skipped")
            continue

        if game_id in positions:
            target = updated[positions[game_id]]
            if event_key(target) != event_key(source):
                metrics["skipped_identity_mismatch"] += 1
                warnings.append(f"{game_id}: team mismatch in existing CSV; skipped")
                continue
            # If an incomplete row already contains an unmatched score, don't overwrite.
            prev_away, prev_home = target.get("away_score", ""), target.get("home_score", "")
            if (prev_away not in ("", str(away)) or prev_home not in ("", str(home))):
                warnings.append(f"{game_id}: existing partial scores conflict; skipped")
                metrics["skipped_score_mismatch"] += 1
                continue
            metrics["filled_finals"] += 1
        else:
            # For newly discovered playoff games, only append after both sources confirm final.
            target = {field: fmt(source.get(field)) for field in headers}
            target["game_id"] = game_id
            updated.append(target)
            positions[game_id] = len(updated) - 1
            metrics["new_finals"] += 1

        target["away_score"] = str(away)
        target["home_score"] = str(home)
        target["result"] = str(home - away)
        target["total"] = str(home + away)
        if not target.get("overtime"):
            target["overtime"] = fmt(source.get("overtime"))

        # Never change a previously recorded point spread or associated odds.
        for field in ("spread_line", "away_spread_odds", "home_spread_odds", "total_line"):
            if field in target and not target.get(field):
                target[field] = fmt(source.get(field))
        if not target.get("spread_line"):
            metrics["without_spread"] += 1
            warnings.append(f"{game_id}: final score saved but no point spread available")

    return updated, metrics, warnings


def write_atomic_csv(path, headers, rows):
    fd, tmp_name = tempfile.mkstemp(prefix=".nfl_games_", suffix=".csv", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv=None):
    today = datetime.now(timezone.utc).date()
    default_season = today.year if today.month >= 8 else today.year - 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=default_season)
    parser.add_argument("--file", type=Path, default=CSV_FILE)
    parser.add_argument("--apply", action="store_true", help="Backup and update CSV. Default is read-only.")
    args = parser.parse_args(argv)
    path = args.file.expanduser().resolve()
    headers, original = load_csv(path)
    print(f"Checking NFL {args.season} | {len(original)} existing games")
    schedule = load_schedule(args.season)
    changed, metrics, warnings = prepare_changes(original, headers, schedule, args.season)
    for key, val in metrics.items():
        print(f"  {key}: {val}")
    for warning in warnings[:15]:
        print(f"  WARNING: {warning}")
    if len(warnings) > 15:
        print(f"  ... and {len(warnings) - 15} more warnings")

    change_count = metrics["new_finals"] + metrics["filled_finals"]
    if not args.apply:
        print("PREVIEW ONLY — no files changed. Use --apply after reviewing.")
        return 0

    backup = None
    if change_count:
        BACKUPS.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = BACKUPS / f"{path.stem}_{ts}_{os.getpid()}.bak.csv"
        shutil.copy2(path, backup)
        write_atomic_csv(path, headers, changed)
        print(f"Backup: {backup}")
        print(f"Updated: {path}")
    else:
        print("Already current, or no new confirmed finals available. CSV unchanged.")
    status_path = path.parent / STATUS_FILE.name
    status_path.write_text(json.dumps({
        "last_checked_utc": datetime.now(timezone.utc).isoformat(),
        "season": args.season, "metrics": metrics,
        "backup": str(backup) if backup else None,
        "csv_updated": bool(change_count)
    }, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"ERROR (CSV unchanged): {e}", file=sys.stderr)
        sys.exit(1)
