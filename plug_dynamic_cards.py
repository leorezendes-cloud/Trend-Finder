"""Compact, read-only presentation data for dynamic Plug research states.

Deliberately separate from official cards until publication migration is ready.
"""
from plug_dynamic_research import snapshot


def card_state(root, game_id, *, as_of_utc, away_team, home_team):
    state=snapshot(root,game_id,as_of_utc=as_of_utc)
    if state["status"]=="unavailable":
        return dict(status="unavailable",ats="Awaiting verified line",
                    ou="Awaiting verified line",note=None,changed=False)
    row=state["revision"]
    if row["ats_selected"]:
        if row["ats_side"] not in (away_team,home_team):
            raise ValueError("Saved ATS team does not match matchup")
        spread=float(row["ats_away_line"])
        side_line=spread if row["ats_side"]==away_team else -spread
        ats=f'{row["ats_side"]} {side_line:+g}'
    else:
        ats="Stay Away"
    ou=f'{row["ou_side"]} {float(row["ou_market_total"]):g}' if row["ou_selected"] else "Stay Away"
    return dict(status=state["status"],ats=ats,ou=ou,
                changed=state["revisions"]>1,
                note="Picks may change with line movement. Final selections lock at kickoff." if state["status"]=="pregame" else "Final pregame selections",
                updated_at=row["evaluated_utc"])
