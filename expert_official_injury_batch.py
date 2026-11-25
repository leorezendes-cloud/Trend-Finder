"""Bounded, forward-only official NFL injury observation batch.

Run from an existing worker/cron; never import candidates as verified reports.
"""
import argparse
import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from expert_official_injury_collect import fetch_official_injury_page, preflight_game


def upcoming_games(schedule, now, horizon_hours=168):
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    found, seen = [], set()
    with Path(schedule).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("game_type") != "REG":
                continue
            try:
                season, week = int(row["season"]), int(row["week"])
                game_id = row["game_id"]
                away, home = row["away_team"], row["home_team"]
                if (not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", game_id)
                        or not re.fullmatch(r"[A-Z]{2,3}", away)
                        or not re.fullmatch(r"[A-Z]{2,3}", home) or away == home):
                    continue
                kickoff = datetime.fromisoformat(row["gameday"] + "T" + row["gametime"])
                if kickoff.tzinfo is not None:
                    continue
                kickoff = kickoff.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
            except (ValueError, KeyError, TypeError):
                continue
            if not now < kickoff <= now + timedelta(hours=horizon_hours):
                continue
            key = (season, week, game_id)
            if key in seen:
                raise ValueError("Duplicate upcoming Scout game: " + game_id)
            seen.add(key)
            found.append({"season": season, "week": week, "game_id": game_id,
                          "away_team": away, "home_team": home, "kickoff_utc": kickoff.isoformat()})
    return sorted(found, key=lambda g: (g["kickoff_utc"], g["game_id"]))


def collect(schedule, destination, now=None, fetch=fetch_official_injury_page):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError("Unsafe destination")
    games = upcoming_games(schedule, now)
    results, pages = [], {}
    # At most one official page fetch per season/week, never after kickoff.
    for game in games:
        key = game["season"], game["week"]
        if key not in pages:
            try:
                pages[key] = fetch(*key)
            except (OSError, ValueError) as exc:
                pages[key] = None
                results.append({"week": key[1], "error": str(exc)[:150]})
        page = pages[key]
        if page is None:
            continue
        cutoff = datetime.now(timezone.utc)
        audit = preflight_game(page, game, cutoff.isoformat())
        if not audit["structural_preflight_passed"]:
            results.append({"game_id": game["game_id"], "issues": audit["issues"]})
            continue
        observed = datetime.fromisoformat(page["retrieved_at"].replace("Z", "+00:00"))
        if not observed <= cutoff < datetime.fromisoformat(game["kickoff_utc"]):
            continue
        folder = destination / str(game["season"]) / f'{game["week"]:02d}'
        folder.mkdir(parents=True, exist_ok=True)
        # A bounded single latest snapshot per game, updated atomically.
        path = folder / (game["game_id"] + ".json")
        teams = set((game["away_team"], game["home_team"]))
        selected = [c for c in page["unverified_table_candidates"] if c.get("team") in teams]
        record = {"schema": 1, "verified_player_records": False,
                  "publication_time_verified": False, "published_at": None,
                  "source_url": page["source_url"], "observed_at": page["retrieved_at"],
                  "game": game, "game_preflight": audit,
                  "unverified_table_candidates": selected}
        payload = json.dumps(record, separators=(",", ":")).encode()
        if len(payload) > 65536:
            results.append({"game_id": game["game_id"], "error": "record_too_large"})
            continue
        # Refuse to overwrite newer observations and never follow symlinks.
        if path.is_symlink():
            raise ValueError("Unsafe observation path")
        if path.exists():
            try:
                old = json.loads(path.read_text())
                old_time = datetime.fromisoformat(old["observed_at"].replace("Z", "+00:00"))
                if old_time >= observed:
                    continue
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("Invalid existing observation; manual review required")
        import tempfile
        fd, temporary = tempfile.mkstemp(prefix=".injury-", dir=folder)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        results.append({"game_id": game["game_id"], "saved": str(path)})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", default="nfl_games.csv")
    parser.add_argument("--destination", default="data/expert_official_observations")
    args = parser.parse_args()
    print(json.dumps(collect(args.schedule, args.destination), indent=2))


if __name__ == "__main__":
    main()
