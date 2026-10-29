"""Read-only ATS/O-U grading of a saved dynamic closing research revision.

Never grade using refreshed market quotes, and never reinterpret the selection
that was actually saved before kickoff. Not connected to official records.
"""
import math
from plug_dynamic_research import snapshot


def closing_grade(root, game_id, *, as_of_utc, away_score, home_score):
    state=snapshot(root,game_id,as_of_utc=as_of_utc)
    if state["status"]!="locked":
        return {"status":state["status"],"ats":None,"ou":None}
    row=state["revision"]
    a=float(away_score); h=float(home_score)
    if not all(math.isfinite(x) for x in (a,h)):
        raise ValueError("Invalid final scores")
    ats=None
    if row["ats_selected"]:
        if row["ats_side"] not in game_id.split("_")[-2:]:
            raise ValueError("Invalid saved ATS team")
        away_team,home_team=game_id.split("_")[-2:]
        edge=a-h+float(row["ats_away_line"])
        ats="Push" if edge==0 else ("Win" if (edge>0)==(row["ats_side"]==away_team) else "Loss")
    ou=None
    if row["ou_selected"]:
        edge=a+h-float(row["ou_market_total"])
        ou="Push" if edge==0 else ("Win" if (edge>0)==(row["ou_side"]=="Over") else "Loss")
    return {"status":"locked","ats":ats,"ou":ou,
            "revision":row["revision"],"quote_observed_utc":row["quote_observed_utc"]}
