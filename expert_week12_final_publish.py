"""One-time owner review/publish of the final 2026 Week 12 CAR@TB Expert replacement.

Default is read-only. --approve-and-publish requires explicit owner action.
"""
import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from expert_beta import Store, canonical, identity, validate_expert

VERSION = "0a9edf3ab03e0cf8697a137ae655a68a0e181240af2a15a6bbc7662e88fd5456"
NAME = VERSION + ".replacement-1.json"


def run(root, execute=False):
    root = Path(root)
    draft_path = root / "drafts" / NAME
    original = json.loads(draft_path.read_text())
    if original.get("review_status") != "pending":
        raise ValueError("Expected original pending replacement draft")
    rows = Store(root).records()
    imports = [r for r in rows if r["version"] == VERSION and r["kind"] == "production_import"]
    if len(imports) != 1:
        raise ValueError("Expected exactly one sealed production import")
    source = imports[0]["scout"]
    game = source["game"]
    if (int(game["season"]), int(game["week"]), game["away_team"], game["home_team"]) != (2026, 12, "TB", "CAR"):
        raise ValueError("Unexpected game; refuse publication")
    if hashlib.sha256(canonical(source)).hexdigest() != original.get("scout_sha256"):
        raise ValueError("Draft is not attached to expected Scout snapshot")
    approved = [r for r in rows if r.get("expert") is not None and r["scout"] == source]
    if not approved:
        raise ValueError("No previously published Expert report to preserve")
    if any(r["expert"].get("provider_response_id") == original.get("provider_response_id") for r in approved):
        return {"game": "CAR@TB", "state": "already_published", "published_versions": len(approved)}
    result = {"game": "TB@CAR", "draft": NAME, "state": "preview",
              "previously_published_versions": len(approved),
              "summary": original.get("summary"),
              "ats_side": original.get("ats_side"), "total_side": original.get("total_side")}
    if not execute:
        return result
    # Explicit owner approval only after reading the full saved draft.
    report = copy.deepcopy(original)
    report.update(review_status="approved", reviewer="owner",
                  reviewed_at=datetime.now(timezone.utc).isoformat())
    validate_expert(report, source)
    review_path = draft_path.with_name(draft_path.stem + ".review.json")
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    try:
        with review_path.open("xb") as output:
            output.write(payload)
    except FileExistsError:
        if review_path.read_bytes() != payload:
            existing = json.loads(review_path.read_text())
            if {k:v for k,v in existing.items() if k not in ("review_status","reviewer","reviewed_at")} != {k:v for k,v in original.items() if k not in ("review_status","reviewer","reviewed_at")} or existing.get("review_status") != "approved":
                raise ValueError("Conflicting existing review")
            report = existing
    digest = Store(root).append(source, expert=report, kind="development")
    result.update(state="published", archive_digest=digest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--approve-and-publish", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.store, execute=args.approve_and_publish), indent=2))


if __name__ == "__main__":
    main()
