"""Publish machine-validated Comebacks updates only. No force pushes."""
import csv
import io
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SNAP = "data/comeback_leads/2026_snapshot.json"
CSV = "nfl_games.csv"
ALLOWED = {CSV, SNAP}
SCORE_FIELDS = {
    "home_score", "away_score", "result", "total", "overtime"
}

root = Path(__file__).resolve().parent
stage = Path(sys.argv[1]).resolve()
expected = root.parent / "Trend-Finder-Comebacks-Refresh-Pending"

def require(ok, message):
    if not ok:
        raise RuntimeError("PUBLICATION BLOCKED: " + message)

def git(*args):
    result = subprocess.run(
        ["git", *args], cwd=stage,
        capture_output=True, text=True, timeout=120
    )
    if result.returncode:
        raise RuntimeError(
            f"Git command failed: {' '.join(args)}\n"
            + result.stderr[-1500:]
        )
    return result.stdout.strip()

def rows(text):
    reader = csv.DictReader(io.StringIO(text))
    return reader.fieldnames, list(reader)

def publish():
    require(stage == expected.resolve() and stage.is_dir(),
            "Unexpected staging directory")

    changed = set(git("diff", "--name-only", "HEAD").splitlines())
    require(changed and changed <= ALLOWED and SNAP in changed,
            f"Unexpected or incomplete changes: {sorted(changed)}")

    status = git("status", "--porcelain", "--untracked-files=normal")
    require(not any(line.startswith("??") for line in status.splitlines()),
            "Unexpected untracked files")

    require(not git("diff", "--check"),
            "Whitespace errors")

    baseline = git("show", f"HEAD:{CSV}")
    fields_old, old_rows = rows(baseline)
    fields_new, new_rows = rows((stage / CSV).read_text())

    require(fields_old == fields_new
            and len(old_rows) == len(new_rows),
            "CSV schema or game count changed")

    for before, after in zip(old_rows, new_rows):
        require(before["game_id"] == after["game_id"],
                "Game order or identity changed")

        differences = {
            key for key in fields_old
            if before[key] != after[key]
        }
        if not differences:
            continue

        require(
            before["game_id"].startswith("2026_")
            and differences <= SCORE_FIELDS,
            f"Unexpected CSV edits: {before['game_id']}"
        )

        for key in differences:
            require(not before[key].strip()
                    and bool(after[key].strip()),
                    f"Previously recorded data changed: "
                    f"{before['game_id']} {key}")

        try:
            home = float(after["home_score"])
            away = float(after["away_score"])
            result = float(after["result"])
            total = float(after["total"])
            valid = (
                home >= 0 and away >= 0
                and home.is_integer() and away.is_integer()
                and result == home - away
                and total == home + away
            )
        except (ValueError, TypeError):
            valid = False

        require(valid, f"Invalid final: {before['game_id']}")

    previous = json.loads(git("show", f"HEAD:{SNAP}"))
    current = json.loads((stage / SNAP).read_text())

    require(
        current.get("status") == previous.get("status")
        == "requires_manual_review",
        "Snapshot review status unexpectedly changed"
    )
    require(
        current.get("season") == 2026
        and current.get("threshold_points") == 10,
        "Season or comeback threshold changed"
    )

    old_games = previous["games"]
    new_games = current["games"]

    require(
        all(new_games.get(gid) == game
            for gid, game in old_games.items()),
        "Previously audited games changed"
    )

    additions = set(new_games) - set(old_games)
    require(additions, "No new audited games")

    by_id = {r["game_id"]: r for r in new_rows}
    today = datetime.now(ZoneInfo("America/New_York")).date()

    for gid in additions:
        require(
            gid in by_id
            and date.fromisoformat(by_id[gid]["gameday"]) < today,
            f"Game not eligible for postgame publication: {gid}"
        )

    sys.path.insert(0, str(stage))
    from comeback_leads import validated_snapshot, coverage

    checked = validated_snapshot(stage)
    require(checked is not None, "Snapshot validation failed")
    require(coverage(checked, stage)["current"],
            "Some completed games remain unaudited")

    base = git("rev-parse", "HEAD")
    git("fetch", "--no-tags", "origin", "main")
    require(git("rev-parse", "FETCH_HEAD") == base,
            "GitHub main changed; retry on next schedule")

    git("add", "--", *sorted(changed))
    git("commit", "-m",
        f"Update verified Comebacks snapshot ({len(new_games)} games)")

    committed = set(git(
        "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).splitlines())
    require(committed == changed,
            "Commit contains unexpected files")

    git("fetch", "--no-tags", "origin", "main")
    require(git("rev-parse", "FETCH_HEAD") == base,
            "GitHub changed before push; retry on next schedule")

    git("push", "origin", "HEAD:refs/heads/main")

    print(
        f"AUTO-PUBLISHED: {len(new_games)} audited games, "
        f"{len(additions)} new games.",
        flush=True
    )

if __name__ == "__main__":
    try:
        publish()
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
