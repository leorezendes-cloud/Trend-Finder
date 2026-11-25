"""Read-only Expert evidence preflight; no network, refresh, draft, or writes.

Usage:
  python -m expert_evidence_diagnostic --store /var/data/expert_beta \\
      --season 2026 --week 12 --game GB@LA
"""
import argparse
import json
from pathlib import Path

from expert_beta import Store, clock, instant
from expert_matchup_evidence import snapshot
from expert_provider import source_facts
from scout4.personnel import _json_rows
from scout4.stats import team_code


def inspect(store, season, week, game, root=None, now=None):
    now = now or clock()
    away, home = game.upper().split("@", 1)
    candidates = []
    for row in Store(store).records():
        if row.get("kind") != "production_import":
            continue
        g = row["scout"]["game"]
        if (int(g["season"]) == season and int(g["week"]) == week
                and g["away_team"] == away and g["home_team"] == home):
            candidates.append(row)
    if not candidates:
        return {"status": "game_not_found", "game": game}
    row = max(candidates, key=lambda item: (item["generated_at"], item["version"]))
    scout = row["scout"]
    kickoff = instant(scout["game"]["kickoff_utc"])
    if now >= kickoff:
        return {"status": "past_kickoff", "game": game,
                "note": "No retrospective evidence refresh or report generation attempted."}
    context = snapshot(scout, root=root, as_of=now)
    independent = {"game": scout["game"], "quotes": scout.get("quotes", {}),
                   "editorial_pregame_context": context}
    facts = source_facts(independent)
    efficiency = context.get("observed_team_efficiency", {})
    personnel = (context.get("personnel") or {}).get("teams", {})
    # Report source coverage without treating missing injury rows as healthy.
    personnel_root = Path(root or Path(__file__).resolve().parent) / "data" / "scout4" / "personnel"
    source_snapshots = []
    for path in sorted((personnel_root / str(season)).glob("*/pregame_evidence.json"))[-8:]:
        try:
            data = json.loads(path.read_text())
            source_snapshots.append({
                "snapshot": path.parent.name,
                "retrieved_at": data.get("manifest", {}).get("retrieved_at"),
                "injury_feed_rows": data.get("manifest", {}).get("files", {}).get("injuries", {}).get("rows"),
                "game_in_snapshot": any(
                    g.get("game_id") == scout["game"].get("game_id")
                    for g in data.get("games", [])),
                "game_injury_rows": {
                    team: len((g.get("personnel", {}).get(team) or {}).get("injury_rows", []))
                    for g in data.get("games", [])
                    if g.get("game_id") == scout["game"].get("game_id")
                    for team in (away, home)},
            })
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    # Aggregate the latest archived injury feed; never print player identities.
    injury_match_diagnostic = {"status": "no_saved_feed"}
    manifests = sorted((personnel_root / str(season)).glob("*/manifest.json"))
    if manifests:
        manifest_path = manifests[-1]
        try:
            manifest = json.loads(manifest_path.read_text())
            injury_path = Path(manifest["files"]["injuries"]["path"])
            if not injury_path.is_absolute():
                injury_path = Path(root or Path(__file__).resolve().parent) / injury_path
            counts = {team: {"team_rows": 0, "season_rows": 0,
                             "week_rows": 0, "season_type_rows": 0,
                             "observed_weeks": {}, "observed_season_types": {},
                             "observed_team_codes": {}} for team in (away, home)}
            for injury in _json_rows(injury_path):
                raw_team = str(injury.get("team", ""))
                normalized = team_code(raw_team)
                if normalized not in counts:
                    continue
                c = counts[normalized]
                c["team_rows"] += 1
                c["observed_team_codes"][raw_team] = c["observed_team_codes"].get(raw_team, 0) + 1
                if str(injury.get("season")) != str(season):
                    continue
                c["season_rows"] += 1
                w = str(injury.get("week"))
                c["observed_weeks"][w] = c["observed_weeks"].get(w, 0) + 1
                typ = str(injury.get("season_type"))
                c["observed_season_types"][typ] = c["observed_season_types"].get(typ, 0) + 1
                if w != str(week):
                    continue
                c["week_rows"] += 1
                if injury.get("season_type") == scout["game"].get("game_type", "REG"):
                    c["season_type_rows"] += 1
            injury_match_diagnostic = {
                "status": "inspected", "snapshot": manifest_path.parent.name,
                "expected_season": season, "expected_week": week,
                "expected_season_type": scout["game"].get("game_type", "REG"),
                "team_counts": counts,
                "note": "Aggregated archived feed only; no names or injury claims."}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            injury_match_diagnostic = {"status": "inspection_error",
                                       "error_type": type(exc).__name__}
    result = {
        "status": "ready_for_review" if efficiency else "missing_team_efficiency",
        "game": game, "checked_at": now.isoformat(),
        "read_only": True, "paid_requests": 0,
        "pregame_cutoff_exclusive": context.get("cutoff_date_exclusive"),
        "team_form_games": {x["team"]: len(x.get("recent", []))
                            for x in context.get("team_form", [])},
        "efficiency_feed_teams": list(efficiency),
        "efficiency_sample_games": {
            team: (data.get("season_to_date") or {}).get("games_with_feed")
            for team, data in efficiency.items()},
        "efficiency_metrics": {
            team: data.get("season_to_date") for team, data in efficiency.items()},
        "defensive_opponent_production": {
            team: {
                "season_to_date": data.get("opponent_production_allowed_season_to_date"),
                "recent_five": data.get("opponent_production_allowed_recent_five"),
            } for team, data in efficiency.items()},
        "personnel_source_snapshots": source_snapshots,
        "injury_match_diagnostic": injury_match_diagnostic,
        "personnel_injury_coverage": {
            team: data.get("injury_coverage") for team, data in personnel.items()},
        "provider_receives_efficiency": bool(facts.get("observed_team_efficiency")),
        "limitations": context.get("limitations", []),
    }
    if not all((efficiency.get(team) or {}).get("season_to_date", {}).get("games_with_feed", 0)
               for team in (away, home)):
        result["status"] = "incomplete_team_efficiency"
    if not result["provider_receives_efficiency"]:
        result["status"] = "provider_packet_missing_efficiency"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--game", required=True, help="AWAY@HOME, e.g. GB@LA")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(inspect(args.store, args.season, args.week,
                             args.game, root=args.root), indent=2))


if __name__ == "__main__":
    main()
