"""Stage conservative Week 9 Expert copyedits; never approve or publish automatically.

Default prints proposed changes. --write creates independent, pending-review
copies under drafts/editorial_week9. Originals, reviewed reports, immutable
forecasts, and all picks stay untouched. No API calls.
"""
import argparse
import copy
import json
from pathlib import Path

from expert_beta import Store

EDIT_RULES = {
    ("TB", "CHI"): [
        (
            "Mayfield is expected as QB1 and full participation is a meaningful sign, but it remains an expected starter, not a confirmed one.",
            "Mayfield is expected to start, and his full practice participation is an encouraging availability signal.",
        ),
    ],
    ("GB", "NE"): [
        (
            "Love is expected, not officially confirmed; Maye is also expected and has full participation in practice, which is the strongest availability signal in the file.",
            "Love is expected to start; Maye is also expected to start and participated fully in practice.",
        ),
    ],
    ("LA", "WAS"): [
        (
            "The personnel snapshot is current, but depth-chart status is still expected rather than confirmed, so the injury report should be read as a live pregame indicator, not a final announcement.",
            "The current practice report provides useful availability signals, though final game-day designations may still change.",
        ),
    ],
    ("ARI", "SEA"): [
        (
            "Because the quarterback depth chart is current and not marked stale, Gardner Minshew II and Sam Darnold remain the expected starters unless later injury news says otherwise.",
            "Gardner Minshew II and Sam Darnold are the expected starters based on the available depth-chart evidence.",
        ),
    ],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default="/var/data/expert_beta")
    parser.add_argument("--write", action="store_true", help="Create pending-review editorial copies")
    args = parser.parse_args()
    root = Path(args.store)
    records = {r["version"]: r for r in Store(root).records()}
    folder = root / "drafts"
    staged = root / "drafts" / "editorial_week9"
    count = changes = 0

    for source in sorted(folder.glob("*.replacement-*.json")):
        if source.name.endswith((".attempt.json", ".review.json", ".outcome.json")):
            continue
        version = source.name.split(".replacement-", 1)[0]
        original = records.get(version)
        if original is None:
            continue
        game = original["scout"]["game"]
        if (int(game["season"]), int(game["week"])) != (2026, 9):
            continue
        report = json.loads(source.read_text(encoding="utf-8"))
        revised = copy.deepcopy(report)
        matchup = (game["away_team"], game["home_team"])
        applied = []
        for section in revised.get("sections", []):
            if not isinstance(section.get("text"), str):
                continue
            for before, after in EDIT_RULES.get(matchup, []):
                if before in section["text"]:
                    section["text"] = section["text"].replace(before, after)
                    applied.append((before, after))
        # Preserve exact conclusions, sourcing, versions and original content.
        for field in ("ats_side", "total_side", "scout_sha256", "editorial_sources",
                      "editorial_as_of", "decision_policy", "generated_at",
                      "provider", "model", "provider_response_id"):
            assert revised.get(field) == report.get(field), field
        # Editorial copies must undergo independent operator review.
        revised["review_status"] = "pending"
        revised.pop("reviewer", None)
        revised.pop("reviewed_at", None)
        count += 1
        changes += len(applied)
        print(f'{matchup[0]} @ {matchup[1]}: {len(applied)} wording edit(s)')
        for before, after in applied:
            print("  OLD:", before)
            print("  NEW:", after)
        if args.write:
            staged.mkdir(parents=True, exist_ok=True)
            dest = staged / source.name
            with dest.open("x", encoding="utf-8") as stream:
                json.dump(revised, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
    print(f"Week 9 replacement copies: {count}; editorial substitutions: {changes}")
    print("Originals untouched. Copies are NOT approved or published.")
    if not args.write:
        print("Use --write to stage independent copies after reviewing changes.")


if __name__ == "__main__":
    main()
