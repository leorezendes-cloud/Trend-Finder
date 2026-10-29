"""Opt-in authoritative dynamic Plug presentation and grading overlay.

Only explicitly saved, verified pregame decisions may replace legacy picks.
After kickoff an immutable closing receipt is mandatory; unavailable means
legacy picks stay visible instead of silently fabricating a closing pick.
"""
from plug_dynamic_cards import card_state
from plug_dynamic_closing import read_closing
from plug_dynamic_closing_grade import grade_closing
from plug_dynamic_journal import _time
from plug_dynamic_research import snapshot


def attach(root, item, *, as_of_utc):
    game = item["scout"]["game"]
    game_id = game["game_id"]
    kickoff = _time(game["kickoff_utc"])
    now = _time(as_of_utc)
    if now < kickoff:
        card = card_state(root, game_id, as_of_utc=as_of_utc,
                          away_team=game["away_team"], home_team=game["home_team"],
                          kickoff_utc=game["kickoff_utc"])
        if card["status"] != "pregame":
            return False
    else:
        receipt = read_closing(root, game_id)
        if receipt is None:
            return False
        if _time(receipt["kickoff_utc"]) != kickoff:
            raise ValueError("Closing receipt kickoff differs from schedule")
        # The preview must read the same locked revision identified in receipt.
        card = card_state(root, game_id, as_of_utc=as_of_utc,
                          away_team=game["away_team"], home_team=game["home_team"],
                          kickoff_utc=game["kickoff_utc"])
        if card["status"] != "locked":
            raise ValueError("Closing receipt has no locked revision")
    if item.get("url", "").startswith("/the-plug/"):
        item["url"] = item["url"].split("?", 1)[0]
    item["plug_dynamic_official"] = True
    item["plug_dynamic_card"] = card
    if now >= kickoff and item.get("final_score") is not None:
        final = item["final_score"]
        result = grade_closing(root, game_id, away_score=final["away"],
                               home_score=final["home"])
        if result["status"] != "locked":
            raise ValueError("Closing grades are unavailable")
        item["plug_dynamic_grades"] = result
    row = snapshot(root, game_id, as_of_utc=as_of_utc)['revision']
    item['plug_ats_policy'] = 'dynamic-plug-v1'
    item['plug_ats_decision'] = dict(row, selected=row['ats_selected'],
        side=row['ats_side'], away_line=row['ats_away_line'],
        away_team=game['away_team'], home_team=game['home_team'], policy='dynamic-plug-v1')
    item['plug_ou_receipt'] = dict(row, selected=row['ou_selected'],
        side=row['ou_side'], market_total=row['ou_market_total'], policy='dynamic-plug-v1')
    item['plug_ats_status'] = 'selected' if row['ats_selected'] else 'stay_away'
    item['plug_ats_pick'] = card['ats'] if row['ats_selected'] else None
    item['plug_ou_status'] = 'selected' if row['ou_selected'] else 'stay_away'
    item['plug_ou_pick'] = card['ou'] if row['ou_selected'] else None
    grades = item.get('plug_dynamic_grades', {})
    item['plug_ats_result'] = grades.get('ats') or ('Pending' if row['ats_selected'] else None)
    item['plug_ou_result'] = grades.get('ou') or ('Pending' if row['ou_selected'] else None)
    item.setdefault('completed_grades', {}).update(
        plug_ats=item['plug_ats_result'], plug_total=item['plug_ou_result'])
    return True
