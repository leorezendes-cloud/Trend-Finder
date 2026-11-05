"""Publish operator-approved Week 9 replacement reports in one guarded batch.

Default is read-only. --approve-and-publish requires a named human reviewer.
No AI calls, no mutation of any original draft, Scout receipt, or existing report.
This command does NOT perform human factual review; reviewer must have reviewed
reports and their supporting evidence before using the write option.
"""
import argparse
import copy
import json
from pathlib import Path

from expert_beta import Store, clock, identity, instant, validate_expert

SEASON, WEEK = 2026, 9


def candidates(root):
    store = Store(root)
    records = store.records()
    by_version = {record["version"]: record for record in records}
    published = {identity(record["scout"]) for record in records if record.get("expert") is not None}
    folder = root / "drafts" / "editorial_week9"
    matches = {}
    for path in sorted(folder.glob("*.replacement-*.json")):
        if path.name.endswith((".attempt.json", ".review.json", ".outcome.json")):
            continue
        version = path.name.split(".replacement-", 1)[0]
        original = by_version.get(version)
        if original is None or original.get("kind") != "production_import":
            continue
        game = original["scout"]["game"]
        if (int(game["season"]), int(game["week"])) != (SEASON, WEEK):
            continue
        game_key = identity(original["scout"])
        if game_key in published:
            continue
        if game_key in matches:
            raise ValueError("Multiple staged replacements for " + game_key)
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("review_status") != "pending":
            raise ValueError("Unexpected staged review state: " + path.name)
        if instant(game["kickoff_utc"]) <= clock():
            raise ValueError("Kickoff has passed; refuse new pregame publication for " + game_key)
        matches[game_key] = (original, path, report)
    return store, matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="/var/data/expert_beta")
    parser.add_argument("--approve-and-publish", action="store_true")
    parser.add_argument("--reviewer", help="Real human reviewer who examined each full report and evidence")
    args = parser.parse_args()
    if args.approve_and_publish and not (args.reviewer and args.reviewer.strip()):
        parser.error("--reviewer is required for human approval")
    if args.reviewer and not args.approve_and_publish:
        parser.error("--reviewer is only used with --approve-and-publish")

    root = Path(args.store)
    store, matches = candidates(root)
    prepared = []
    timestamp = clock().isoformat()
    for key, (original, path, report) in sorted(matches.items()):
        approved = copy.deepcopy(report)
        approved["review_status"] = "approved"
        approved["reviewer"] = args.reviewer.strip() if args.reviewer else "PREVIEW_ONLY"
        approved["reviewed_at"] = timestamp
        validate_expert(approved, original["scout"])
        target = path.with_name(path.stem + ".review.json")
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            validate_expert(existing, original["scout"])
            if (existing.get("ats_side"), existing.get("total_side"),
                    existing.get("scout_sha256")) != (
                    approved.get("ats_side"), approved.get("total_side"),
                    approved.get("scout_sha256")):
                raise ValueError("Existing approved review conflicts: " + str(target))
            approved = existing
        prepared.append((key, original, target, approved))
        print(f'{key}: {approved.get("ats_side") or "Pass"} ATS / {approved.get("total_side") or "Pass"} total')
    print(f"Structurally validated unpublished reports: {len(prepared)}")
    if not args.approve_and_publish:
        print("READ ONLY. No approvals or publications performed.")
        return
    if not prepared:
        print("Nothing to publish; existing published Expert records preserved.")
        return
    # Only after ALL reports have passed checks do any writes begin.
    for key, original, target, approved in prepared:
        if not target.exists():
            with target.open("x", encoding="utf-8") as stream:
                json.dump(approved, stream, sort_keys=True, indent=2, ensure_ascii=False)
                stream.write("\n")
        digest = store.append(original["scout"], expert=approved, kind="development")
        print(f"PUBLISHED {key}: {digest}")
    print("Approved records appended immutably. No original report or Scout data overwritten.")


if __name__ == "__main__":
    main()
