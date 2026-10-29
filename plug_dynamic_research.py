"""Research-only orchestration of verified pregame dynamic decisions.

Not wired to production display or grading. A successful call writes at most
one change to the append-only research journal.
"""
from datetime import datetime, timezone
from plug_dynamic_market import verified_decision
from plug_dynamic_journal import append, read


def observe(root, *, game_id, away_team, home_team, kickoff_utc,
            model_away_spread, v14_total, original_total_side, evaluation_utc):
    state=verified_decision(root,game_id=game_id,away_team=away_team,
        home_team=home_team,kickoff_utc=kickoff_utc,
        model_away_spread=model_away_spread,v14_total=v14_total,
        original_total_side=original_total_side,evaluation_utc=evaluation_utc)
    return append(root,game_id,state)


def snapshot(root, game_id, *, as_of_utc):
    """Read last historically observed revision; never invent a closing pick.

    If there was no pre-kickoff revision, report unavailable. At/after kickoff,
    last actually saved revision becomes the research closing state. Historical
    official grades are still calculated independently from original receipts.
    """
    at=datetime.fromisoformat(as_of_utc.replace("Z","+00:00"))
    if at.tzinfo is None:
        raise ValueError("Timezone required")
    at=at.astimezone(timezone.utc)
    history=read(root,game_id)
    valid=[r for r in history if
           datetime.fromisoformat(r["evaluated_utc"])<=at]
    if not valid:
        return {"status":"unavailable","revision":None}
    last=valid[-1]
    kick=datetime.fromisoformat(last["kickoff_utc"])
    return {"status":"locked" if at>=kick else "pregame",
            "revision":last,"revisions":len(valid)}
