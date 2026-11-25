"""One-time operator recovery for Week 12 Expert drafts after expired API key.

Run from the deployed repository: python -m expert_week12_recovery --execute
Default is preview. This never approves or publishes reports.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path

from expert_beta import Store, clock, identity, instant
from expert_auto_queue import (BudgetExhausted, openai_draft, production_queue,
                               recent_attempts, refresh_expert_evidence, week_usage)

WEEK = (2026, 12)
MAX_USD = 5
ARCHIVE = "expired-key-week12"


def run(root, execute=False, max_requests=4):
    root = Path(root)
    folder = root / "drafts"
    archive = folder / ARCHIVE
    if not 1 <= max_requests <= 4:
        raise ValueError("max_requests must be between 1 and 4")
    if not root.is_dir():
        raise ValueError("Expert store not found")
    if execute and os.environ.get("TREND_FINDAH_EXPERT_AUTO_DRAFT") != "1":
        raise ValueError("Expert drafting not enabled")
    model = os.environ.get("EXPERT_AI_MODEL")
    if not model:
        raise ValueError("EXPERT_AI_MODEL missing")
    with (root / "automation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = Store(root).records()
        queue, counts = production_queue(root)
        latest = {}
        for row in records:
            if row.get("kind") != "production_import":
                continue
            game = row["scout"]["game"]
            if (int(game["season"]), int(game["week"])) != WEEK or instant(game["kickoff_utc"]) <= clock():
                continue
            key = identity(row["scout"])
            if key not in latest or (row["generated_at"], row["version"]) > (latest[key]["generated_at"], latest[key]["version"]):
                latest[key] = row
        recover = []
        for row in latest.values():
            v = row["version"]
            attempt, outcome = folder / (v + ".attempt.json"), folder / (v + ".outcome.json")
            if not attempt.exists() or not outcome.exists():
                continue
            a, o = json.loads(attempt.read_text()), json.loads(outcome.read_text())
            if (a.get("nfl_week") != list(WEEK) or a.get("model") != model
                    or o.get("state") != "uncertain" or o.get("error_type") != "RuntimeError"
                    or o.get("failure_stage") != "provider_request"):
                continue
            if (folder / (v + ".json")).exists() or list(folder.glob(v + ".retry-*.attempt.json")):
                continue
            if (archive / attempt.name).exists() or (archive / outcome.name).exists():
                raise ValueError("Partial recovery archive for " + v)
            recover.append((row, attempt, outcome))
        recover.sort(key=lambda item: instant(item[0]["scout"]["game"]["kickoff_utc"]))
        if execute and recover:
            archive.mkdir(exist_ok=True)
            for row, attempt, outcome in recover:
                attempt.rename(archive / attempt.name)
                outcome.rename(archive / outcome.name)
        queue, counts = production_queue(root)
        targets = [row for row in queue if (int(row["scout"]["game"]["season"]),
                    int(row["scout"]["game"]["week"])) == WEEK]
        spent, requests = week_usage(root, records, WEEK)
        used = len(recent_attempts(root, clock()))
        output = dict(state="preview" if not execute else "complete",
                      archived_failures=len(recover), eligible=len(targets),
                      week12_reserved_usd=str(spent), week12_requests=requests,
                      attempts_last_24h=used, saved_drafts=0)
        if not execute:
            return output
        if spent >= MAX_USD or requests >= 32 or used >= 16:
            output["state"] = "budget_or_daily_limit"
            return output
        if not targets:
            return output
        refresh_expert_evidence(clock())
        records = Store(root).records()
        for row in targets[:min(max_requests, 16-used, 32-requests)]:
            if instant(row["scout"]["game"]["kickoff_utc"]) <= clock():
                continue
            try:
                state = openai_draft(root, row, records, model, MAX_USD, 32, 16)
                if state != "saved":
                    output["state"] = state
                    break
                output["saved_drafts"] += 1
            except BudgetExhausted:
                output["state"] = "budget_exhausted"
                break
            except Exception as error:
                output["state"] = "operator_review_required"
                output["error_type"] = type(error).__name__
                break
        return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--store", default="/var/data/expert_beta")
    args = parser.parse_args()
    print(json.dumps(run(args.store, args.execute, args.max_requests), indent=2))
