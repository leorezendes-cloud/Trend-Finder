#!/usr/bin/env python3
"""Mike's pre-specified >=65% ATS-handle fade study.

READ-ONLY: Loads documented, pre-kickoff sportsbook snapshots from
ats_handle_snapshots.csv, grades against completed games in nfl_games.csv,
and summarizes all/primetime/playoff games. Never invents missing splits.

This is descriptive historical research, not proof of a betting edge.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SNAPSHOTS = ROOT / "ats_handle_snapshots.csv"
GAMES = ROOT / "nfl_games.csv"
THRESHOLD = 65.0
REQUIRED = {
    "game_id", "kickoff_utc", "captured_at_utc", "away_team", "home_team",
    "away_spread", "away_handle_pct", "home_handle_pct", "sportsbook", "source_url",
}
POSTSEASON = {"WC", "DIV", "CON", "SB"}


def utc_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("A timezone is required")
    return stamp.astimezone(timezone.utc)


def snapshot_from_row(row: dict) -> dict:
    if not all(row.get(field, "").strip() for field in REQUIRED):
        raise ValueError("Missing a required snapshot field")
    if urlparse(row["source_url"].strip()).scheme not in ("https", "http"):
        raise ValueError("Invalid source URL")

    kickoff = utc_time(row["kickoff_utc"])
    captured = utc_time(row["captured_at_utc"])
    if captured >= kickoff:
        raise ValueError("Snapshot captured at/after kickoff")

    away_pct = float(row["away_handle_pct"])
    home_pct = float(row["home_handle_pct"])
    away_spread = float(row["away_spread"])
    if not math.isfinite(away_spread):
        raise ValueError("Spread must be finite")
    if not (0 <= away_pct <= 100 and 0 <= home_pct <= 100):
        raise ValueError("Handle percentages outside 0–100")
    if abs((away_pct + home_pct) - 100) > 1.1:
        raise ValueError("Handle percentages do not total approximately 100")

    return {
        "game_id": row["game_id"].strip(),
        "kickoff": kickoff,
        "captured": captured,
        "away_team": row["away_team"].strip().upper(),
        "home_team": row["home_team"].strip().upper(),
        "away_spread": away_spread,
        "away_handle_pct": away_pct,
        "home_handle_pct": home_pct,
        "sportsbook": row["sportsbook"].strip(),
        "source_url": row["source_url"].strip(),
    }


def load_games(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        from pregame_lines import effective_rows
        return {row["game_id"]: row for row in effective_rows(csv.DictReader(handle),path)}


def summarize(records: list[dict]) -> dict:
    graded = [r for r in records if r["result"] in ("Win", "Loss", "Push")]
    wins = sum(r["result"] == "Win" for r in graded)
    losses = sum(r["result"] == "Loss" for r in graded)
    pushes = sum(r["result"] == "Push" for r in graded)
    decisions = wins + losses
    return {
        "qualifying": len(records),
        "graded": len(graded),
        "pending": len(records) - len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "ats_pct": round(100 * wins / decisions, 1) if decisions else None,
    }


def analyze(snapshots_path: Path = SNAPSHOTS, games_path: Path = GAMES) -> dict:
    if not snapshots_path.exists():
        raise FileNotFoundError(f"Missing {snapshots_path.name}. Create its header first.")
    if not games_path.exists():
        raise FileNotFoundError(f"Missing {games_path.name}.")
    games = load_games(games_path)

    total = rejected = 0
    latest: dict[tuple[str, str], dict] = {}
    with snapshots_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError("ATS snapshot CSV is missing required column headers")
        for row in reader:
            total += 1
            try:
                snap = snapshot_from_row(row)
                game = games.get(snap["game_id"])
                if game is None:
                    raise ValueError("Unknown game_id")
                if (snap["away_team"] != game["away_team"]
                        or snap["home_team"] != game["home_team"]):
                    raise ValueError("Team/game_id mismatch")
                # Keep the latest valid pregame observation per game and sportsbook.
                key = (snap["game_id"], snap["sportsbook"].casefold())
                old = latest.get(key)
                if old is None or snap["captured"] > old["captured"]:
                    latest[key] = snap
            except (ValueError, TypeError, OverflowError, KeyError):
                rejected += 1

    records = []
    for snap in latest.values():
        away_pct = snap["away_handle_pct"]
        home_pct = snap["home_handle_pct"]
        if max(away_pct, home_pct) < THRESHOLD:
            continue

        heavily_backed = (snap["away_team"] if away_pct >= THRESHOLD
                          else snap["home_team"])
        fade_side = (snap["home_team"] if away_pct >= THRESHOLD
                     else snap["away_team"])
        money_pct = max(away_pct, home_pct)
        game = games[snap["game_id"]]
        result = "Pending"
        if game.get("away_score", "").strip() and game.get("home_score", "").strip():
            away_ats_margin = (float(game["away_score"]) - float(game["home_score"])
                               + snap["away_spread"])
            fade_ats_margin = (away_ats_margin if fade_side == snap["away_team"]
                               else -away_ats_margin)
            result = "Win" if fade_ats_margin > 1e-8 else ("Loss" if fade_ats_margin < -1e-8 else "Push")

        time = game.get("gametime", "").strip()
        primetime = bool(time and time >= "19:00" and game.get("game_type") == "REG")
        playoff = game.get("game_type") in POSTSEASON
        records.append({
            "game_id": snap["game_id"],
            "matchup": f'{snap["away_team"]} @ {snap["home_team"]}',
            "gameday": game.get("gameday", ""),
            "heavily_backed": heavily_backed,
            "fade_pick": fade_side,
            "handle_pct": money_pct,
            "away_spread": snap["away_spread"],
            "result": result,
            "primetime": primetime,
            "playoff": playoff,
            "sportsbook": snap["sportsbook"],
            "source_url": snap["source_url"],
            "captured_at_utc": snap["captured"].isoformat(),
        })

    records.sort(key=lambda r: (r["gameday"], r["game_id"]))
    return {
        "threshold": THRESHOLD,
        "snapshots_read": total,
        "rejected_snapshots": rejected,
        "unique_valid_games": len({s["game_id"] for s in latest.values()}),
        "sportsbooks": sorted({s["sportsbook"] for s in latest.values()}, key=str.casefold),
        "valid_game_sportsbook_pairs": len(latest),
        "handle_records": sorted([
            dict(game_id=snap["game_id"],
                 matchup=f'{snap["away_team"]} @ {snap["home_team"]}',
                 gameday=games[snap["game_id"]].get("gameday", ""),
                 week=games[snap["game_id"]].get("week", ""),
                 season=games[snap["game_id"]].get("season", ""),
                 game_type=games[snap["game_id"]].get("game_type", ""),
                 away_team=snap["away_team"],home_team=snap["home_team"],
                 away_handle_pct=snap["away_handle_pct"],home_handle_pct=snap["home_handle_pct"],
                 away_spread=snap["away_spread"],sportsbook=snap["sportsbook"],
                 source_url=snap["source_url"],captured_at_utc=snap["captured"].isoformat(),
                 qualifies=max(snap["away_handle_pct"],snap["home_handle_pct"]) >= THRESHOLD)
            for snap in latest.values()
        ], key=lambda row: (row["gameday"], row["game_id"], row["sportsbook"])),
        "records": records,
        "all": summarize(records),
        "primetime": summarize([r for r in records if r["primetime"]]),
        "playoffs": summarize([r for r in records if r["playoff"]]),
        "other_regular": summarize([r for r in records if not r["primetime"] and not r["playoff"]]),
    }


def main() -> None:
    report = analyze()
    print("MIKE'S ATS HANDLE STUDY — pregame snapshots only")
    print(f"Snapshots read: {report['snapshots_read']} | Rejected: {report['rejected_snapshots']}")
    print(f"Format-valid pregame matchup records: {report['unique_valid_games']}")
    for sportsbook in report["sportsbooks"]:
        summary = summarize([r for r in report["records"] if r["sportsbook"].casefold() == sportsbook.casefold()])
        print(f"{sportsbook}: {summary}")
    # Pooled figures count game/sportsbook observations, not independent games.
    print("Combined observations (a game can appear at multiple sportsbooks):")
    for label, key in [
        ("ALL GAMES", "all"),
        ("PRIMETIME", "primetime"),
        ("PLAYOFFS", "playoffs"),
        ("OTHER REGULAR", "other_regular"),
    ]:
        s = report[key]
        rate = f"{s['ats_pct']:.1f}%" if s["ats_pct"] is not None else "Not available"
        print(f"{label}: {s['qualifying']} qualifying | "
              f"{s['wins']}-{s['losses']}-{s['pushes']} ATS | "
              f"{s['pending']} pending | Win rate: {rate}")
    if not report["snapshots_read"]:
        print("Awaiting documented pre-kickoff ATS handle snapshots. No win rate calculated.")


if __name__ == "__main__":
    main()
