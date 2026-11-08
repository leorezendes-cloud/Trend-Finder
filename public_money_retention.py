#!/usr/bin/env python3
"""Read-only sizing study for public-money/price history retention.

This script NEVER edits, deletes, truncates, or writes snapshot data. Its
candidate count is NOT clearance to delete: historical sealed pregame receipts
and backtests may need a quote at an exact timestamp.
"""
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKET_FIELDS = ("side_a", "side_b", "line_a", "line_b", "odds_a", "odds_b",
                 "handle_a", "handle_b", "bets_a", "bets_b")
IDENTITY_FIELDS = ("game_id", "market", "sportsbook", "away_team", "home_team",
                   "kickoff_utc")

def stamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Unverified capture timestamp")
    return dt.astimezone(timezone.utc)

def preview(path):
    groups = defaultdict(list)
    total = split_rows = price_rows = 0
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            total += 1
            if not row.get("game_id") or not row.get("market"):
                raise ValueError("Incomplete market identity")
            capture = stamp(row["captured_at_utc"])
            key = tuple(row.get(f, "") for f in IDENTITY_FIELDS)
            groups[key].append((capture, total, row))
            if all(row.get(k) not in ("", None) for k in
                   ("handle_a", "handle_b", "bets_a", "bets_b")):
                split_rows += 1
            else:
                price_rows += 1

    retained = 0
    same_values = 0
    movements = 0
    groups_with_changes = 0
    for observations in groups.values():
        observations.sort(key=lambda item: (item[0], item[1]))
        fingerprints = [tuple(row.get(k, "") for k in MARKET_FIELDS)
                        for _, _, row in observations]
        previous = None
        changed = False
        for i, (capture, _, row) in enumerate(observations):
            fingerprint = fingerprints[i]
            if previous is not None:
                if fingerprint == previous:
                    same_values += 1
                else:
                    movements += 1
                    changed = True
            previous = fingerprint
        groups_with_changes += int(changed)
        # Conservative *illustration* only: opening, closing/latest, every
        # market/split transition and the first observation on each UTC day.
        # These are *candidates*, not a safe compaction policy. Some sealed
        # decisions may depend on otherwise unchanged timestamped quotes.
        keep = set()
        days = set()
        for i, (capture, _, _) in enumerate(observations):
            day = capture.date()
            if i == 0 or day not in days or (
                    i > 0 and fingerprints[i] != fingerprints[i - 1]):
                keep.add(i)
            days.add(day)
        if observations:
            keep.add(len(observations) - 1)
        retained += len(keep)

    size = Path(path).stat().st_size
    return {
        "source": str(path),
        "source_bytes": size,
        "rows": total,
        "groups": len(groups),
        "split_rows": split_rows,
        "price_only_rows": price_rows,
        "unchanged_consecutive_observations": same_values,
        "changed_observations": movements,
        "groups_with_changes": groups_with_changes,
        "illustrative_retained_rows": retained,
        "illustrative_redundant_rows": total - retained,
        "warning": "READ ONLY. This is not an authorized deletion or safe"
                   " compaction set. Exact timestamped quotes can support"
                   " sealed forecasts and historical research."
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    path = args.root / "public_money_snapshots.csv"
    if not path.is_file():
        parser.error(f"Missing snapshot file: {path}")
    print(json.dumps(preview(path), indent=2))

if __name__ == "__main__":
    main()
