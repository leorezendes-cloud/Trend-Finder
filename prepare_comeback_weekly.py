"""Prepare a verified Comebacks update from the latest production main."""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECTS = Path.home() / "IT-Lab/python_projects"
PILOT = PROJECTS / "Lead-Comeback-Pilot"
SOURCE = Path(__file__).resolve().parent

def run(*args, cwd=SOURCE):
    subprocess.run(args, cwd=cwd, check=True)

def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def main():
    if not (PILOT / "lead_pilot_v3.py").is_file():
        raise SystemExit("STOP: Local V3 scoring pilot unavailable.")

    run("git", "fetch", "origin", "main")

    release = PROJECTS / "Trend-Finder-Comebacks-Refresh-Pending"
    if release.exists():
        raise SystemExit("STOP: Previous update awaits review.")
    run("git", "worktree", "add", "--detach", str(release), "origin/main")

    csv_path = release / "nfl_games.csv"
    snapshot_path = release / "data/comeback_leads/2026_snapshot.json"
    template_path = release / "templates/comeback_leads.html"

    original_bytes = csv_path.read_bytes()
    before = rows(csv_path)

    print("\n=== UPDATING VERIFIED FINAL SCORES ===", flush=True)
    run(
        sys.executable, "update_nfl_games.py",
        "--season", "2026",
        "--file", str(csv_path), "--apply",
        cwd=release
    )

    after = rows(csv_path)
    if len(before) != len(after):
        raise SystemExit(
            "STOP: Games were added or removed. Manual review required."
        )


    # Safe score-only normalization v2
    import io
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    scoring = {
        "home_score", "away_score", "result", "total", "overtime"
    }
    market = {
        "spread_line", "away_spread_odds",
        "home_spread_odds", "total_line"
    }

    original_lines = original_bytes.splitlines(keepends=True)

    if len(original_lines) != len(before) + 1:
        raise SystemExit("STOP: Unexpected CSV line layout.")

    cleaned_lines = list(original_lines)
    changed_games = []
    today = datetime.now(ZoneInfo("America/New_York")).date()

    for position, (old, new) in enumerate(zip(before, after), 1):
        gid = old["game_id"]

        if gid != new["game_id"]:
            raise SystemExit("STOP: Game order changed.")

        differences = {
            field for field in old
            if old[field] != new[field]
        }

        if not differences:
            continue

        if not gid.startswith("2026_"):
            raise SystemExit(f"STOP: Unexpected season: {gid}")

        if not differences <= scoring | market:
            raise SystemExit(f"STOP: Unexpected fields: {gid}")

        if any(
            old[field].strip() or not new[field].strip()
            for field in differences
        ):
            raise SystemExit(f"STOP: Existing data changed: {gid}")

        # Never include games from the current day.
        if date.fromisoformat(old["gameday"]) >= today:
            continue

        accepted = differences & scoring

        if not accepted:
            continue

        cleaned = dict(old)

        for field in accepted:
            cleaned[field] = new[field]

        try:
            home = int(cleaned["home_score"])
            away = int(cleaned["away_score"])
            result = int(cleaned["result"])
            total = int(cleaned["total"])
            overtime = int(cleaned["overtime"])

            if (
                min(home, away) < 0
                or result != home - away
                or total != home + away
                or overtime not in (0, 1)
            ):
                raise ValueError("Score inconsistency")
        except (ValueError, TypeError) as exc:
            raise SystemExit(
                f"STOP: Invalid scoring for {gid}: {exc}"
            )

        ending = (
            "\r\n"
            if original_lines[position].endswith(b"\r\n")
            else "\n"
        )

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(
            buffer,
            fieldnames=list(old),
            lineterminator=ending
        )
        writer.writerow(cleaned)

        cleaned_lines[position] = buffer.getvalue().encode("utf-8")
        changed_games.append(gid)

    # Rebuild from original lines, not the updater's modified CSV.
    # Thus all betting market changes are discarded.
    csv_path.write_bytes(b"".join(cleaned_lines))

    print("Verified scoring updates:", len(changed_games))
    print("Historical betting lines preserved.")


    print("\n=== RECONSTRUCTING COMEBACKS ===", flush=True)
    code = (
        "from pathlib import Path; "
        "from refresh_comeback_snapshot import refresh; "
        "refresh(csv_path=Path.cwd()/'nfl_games.csv', "
        "root=Path.cwd(), "
        "pilot=Path.home()/'IT-Lab/python_projects/Lead-Comeback-Pilot')"
    )
    run(sys.executable, "-c", code, cwd=release)

    print("\n=== VALIDATING SEASON COVERAGE ===", flush=True)
    validation = (
        "from pathlib import Path; "
        "from comeback_leads import validated_snapshot, coverage; "
        "d=validated_snapshot(); "
        "assert d is not None, 'Invalid snapshot'; "
        "s=coverage(d); "
        "print('Audited:', d['games_checked'], "
        "'Pending:', s['pending']); "
        "assert s['current'], 'Unverified completed games remain'"
    )
    run(sys.executable, "-c", validation, cwd=release)

    # The leaderboard now always displays all 32 teams.
    # Verify obsolete view toggles have not returned.
    html = template_path.read_text()

    if (
        'class="cb-view"' in html
        or ">Notable teams</a>" in html
        or ">Teams With Events</a>" in html
    ):
        raise SystemExit(
            "STOP: Obsolete team-view controls detected."
        )

    print("32-team leaderboard layout verified.")

    print("\n=== FOCUSED TESTS ===", flush=True)
    run(sys.executable, "-m", "unittest", "-q",
        "test_comeback_leads", cwd=release)

    run("git", "-c", "core.whitespace=cr-at-eol",
        "diff", "--check", cwd=release)

    doc = json.loads(snapshot_path.read_text())
    total = sum(
        team["comeback_wins_10_plus"]
        for team in doc["teams"].values()
    )

    run("git", "restore", "--", "nfl_games_update_status.json", cwd=release)

    print("\n=== PREPARED UPDATE ===")
    print("Games audited:", doc["games_checked"])
    print("Comeback wins:", total)
    print("Review status:", doc["status"])
    print("Release worktree:", release)
    print("\nChanged tracked files:")
    run("git", "status", "--short", "--untracked-files=no", cwd=release)
    print("\nSAFE: No changes committed or pushed.")

if __name__ == "__main__":
    main()
