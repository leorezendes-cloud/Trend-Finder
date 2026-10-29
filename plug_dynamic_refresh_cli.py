"""Explicit, opt-in research refresh for one verified NFL game.

No scheduler hooks or official receipt writes. All inputs are supplied from
independently frozen model forecasts. Prints decision summary after journaling.
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from plug_dynamic_research import observe

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--game-id",required=True)
    parser.add_argument("--away",required=True)
    parser.add_argument("--home",required=True)
    parser.add_argument("--kickoff-utc",required=True)
    parser.add_argument("--v5-away-spread",type=float,required=True)
    parser.add_argument("--v14-total",type=float,required=True)
    parser.add_argument("--original-total-side",choices=("Over","Under"),required=True)
    args=parser.parse_args()
    decision=observe(args.root,game_id=args.game_id,away_team=args.away,
                     home_team=args.home,kickoff_utc=args.kickoff_utc,
                     model_away_spread=args.v5_away_spread,
                     v14_total=args.v14_total,
                     original_total_side=args.original_total_side,
                     evaluation_utc=datetime.now(timezone.utc).isoformat())
    print(json.dumps({"game_id":args.game_id,"revision":decision["revision"],
                      "ats_selected":decision["ats_selected"],
                      "ou_selected":decision["ou_selected"],
                      "evaluated_utc":decision["evaluated_utc"]},sort_keys=True))

if __name__=="__main__":
    main()
