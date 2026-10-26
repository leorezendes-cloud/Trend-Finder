
"""Scheduled, fail-closed Comebacks preparation. Never pushes."""
import fcntl
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT.parent
STAGE = PROJECTS / "Trend-Finder-Comebacks-Refresh-Pending"
LOGS = Path.home() / "Library/Logs/TrendFindah"

def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT,
        capture_output=True, text=True
    )

def main():
    LOGS.mkdir(parents=True, exist_ok=True)

    with (LOGS / "comebacks.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Comebacks refresh is running.")
            return 0

        if STAGE.exists():
            print("Previous update awaits review:", STAGE)
            return 0

        env = dict(
            os.environ,
            GIT_TERMINAL_PROMPT="0",
            GCM_INTERACTIVE="never",
        )

        try:
            result = subprocess.run(
                [sys.executable,
                 str(ROOT / "prepare_comeback_weekly.py")],
                cwd=ROOT, env=env,
                timeout=900, check=False
            )
        except subprocess.TimeoutExpired:
            print("Refresh timed out; staging requires inspection.")
            return 1

        if result.returncode:
            print("Validation failed; nothing published.")
            if STAGE.exists():
                cleanup = git(
                    "worktree", "remove", "--force", str(STAGE)
                )
                if cleanup.returncode:
                    print("Staging cleanup failed:", cleanup.stderr)
            return result.returncode

        if not STAGE.exists():
            print("No staging worktree was produced.")
            return 1

        changed = subprocess.run(
            ["git", "-C", str(STAGE),
             "diff", "--name-only"],
            capture_output=True, text=True, check=True
        ).stdout.splitlines()

        allowed = {
            "nfl_games.csv",
            "data/comeback_leads/2026_snapshot.json",
            "templates/comeback_leads.html",
        }

        if not set(changed) <= allowed:
            print("Unexpected changes. Review required:", changed)
            return 1

        if not changed:
            cleanup = git(
                "worktree", "remove", "--force", str(STAGE)
            )
            if cleanup.returncode:
                print("Cleanup failed:", cleanup.stderr)
                return 1
            print("Already current. No release needed.")
            return 0

        print("Validated changes ready; checking automatic publication.",
              flush=True)
        try:
            published = subprocess.run(
                [sys.executable,
                 str(ROOT / "auto_publish_comebacks.py"),
                 str(STAGE)],
                cwd=ROOT, env=env,
                timeout=300, check=False
            )
        except subprocess.TimeoutExpired:
            print("Publication timed out. Staging retained.")
            return 1

        cleanup = git(
            "worktree", "remove", "--force", str(STAGE)
        )
        if cleanup.returncode:
            print("Staging cleanup failed:", cleanup.stderr)
            return 1

        return published.returncode

if __name__ == "__main__":
    sys.exit(main())
