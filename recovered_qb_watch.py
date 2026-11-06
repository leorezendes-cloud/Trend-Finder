"""Read-only QB availability watch from existing pregame personnel evidence.

This is contextual information, NOT starter verification and NEVER a source of
automatic QB-flip selections. The tracker retains its sourced-report rules.
"""
from datetime import timedelta

from expert_matchup_evidence import _personnel_context


def watch(root, game, now):
    from recovered_nfl_tracker import kickoff
    ko = kickoff(game)
    if ko is None:
        return None
    # Once the game starts, display the last available pregame snapshot,
    # never a post-kickoff personnel update.
    as_of = min(now, ko - timedelta(microseconds=1))
    if as_of.tzinfo is None:
        return None
    scout = {"game": {"game_id": game["game_id"],
                      "season": game["season"],
                      "week": game["week"],
                      "away_team": game["away_team"],
                      "home_team": game["home_team"],
                      "kickoff_utc": ko.isoformat()}}
    personnel, sources = _personnel_context(scout, root, as_of, player_names={})
    if not personnel:
        return None
    teams = {}
    for team in (game["away_team"], game["home_team"]):
        data = personnel.get("teams", {}).get(team) or {}
        expected = data.get("expected_quarterback") or {}
        situation = data.get("quarterback_situation") or {}
        basis = expected.get("basis") or ""
        teams[team] = {
            "name": expected.get("name"),
            "basis": basis,
            "status": expected.get("status") or "Not reported",
            "source_status": ("Operator-recorded expected starter" if basis.startswith("operator-recorded")
                              else "Depth-chart candidate; not a verified starter"),
            "availability_uncertain": situation.get("explain_availability_risk", False),
            "depth_stale": data.get("depth_chart_stale"),
        }
    return {
        "observed_at": personnel["observed_at"],
        "freshness": personnel["freshness"],
        "teams": teams,
        "source": "NFLverse depth chart and injury context",
        "source_url": next((s["url"] for s in sources if s["name"] == "nflverse_personnel"), None),
    }
