"""Fail-closed verified saved-market adapter for isolated Plug research.

Reads spread and total from the same validated saved snapshot API already used
on matchup cards. Does not fetch odds, publish picks or alter sealed receipts.
"""
from datetime import datetime, timezone
import math

from public_pick_market import matchup_public_market
from plug_dynamic_pregame import decide


def verified_decision(root, *, game_id, away_team, home_team, kickoff_utc,
                      model_away_spread, v14_total, original_total_side,
                      evaluation_utc):
    now=datetime.fromisoformat(evaluation_utc.replace("Z","+00:00"))
    kickoff=datetime.fromisoformat(kickoff_utc.replace("Z","+00:00"))
    if now.tzinfo is None or kickoff.tzinfo is None or not now<kickoff:
        raise ValueError("Evaluation must precede verified kickoff")
    market=matchup_public_market(root,dict(game_id=game_id,away=away_team,
         home=home_team,kickoff_at=kickoff_utc),now=now)
    markets=market["markets"]
    keys=[m["key"] for m in markets]
    if len(keys)!=len(set(keys)):
        raise ValueError("Duplicate market entries")
    by_key={m["key"]:m for m in markets}
    quotes=[]
    for kind,names in (("Spread",(away_team,home_team)),
                       ("Total",("Over","Under"))):
        item=by_key.get(kind)
        if not item or item.get("stale") or [s["name"] for s in item["sides"]]!=list(names):
            raise ValueError("Missing, stale or mismatched "+kind+" quote")
        lines=[s.get("line") for s in item["sides"]]
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in lines):
            raise ValueError("Invalid "+kind+" line")
        if kind=="Spread" and abs(lines[0]+lines[1])>1e-9:
            raise ValueError("Conflicting spread lines")
        if kind=="Total" and abs(lines[0]-lines[1])>1e-9:
            raise ValueError("Conflicting total lines")
        observed=datetime.fromisoformat(item["captured"].replace("Z","+00:00"))
        if observed.tzinfo is None or not observed<=now or not observed<kickoff:
            raise ValueError("Invalid "+kind+" observation time")
        quotes.append((item,observed))
    spread,total=[item for item,_ in quotes]
    # Conservative common observation cutoff; both individual quotes were
    # validated before selecting the most recent one.
    observed=max(t for _,t in quotes)
    return decide(away_team=away_team,home_team=home_team,
        model_away_spread=model_away_spread,
        market_away_spread=spread["sides"][0]["line"],
        market_total=total["sides"][0]["line"],v14_total=v14_total,
        original_total_side=original_total_side,
        quote_observed_utc=observed.isoformat(),
        evaluation_utc=now.isoformat(),kickoff_utc=kickoff_utc)
