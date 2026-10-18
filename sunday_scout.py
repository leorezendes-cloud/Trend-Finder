"""Optional Trend Findah 3000 Sunday Scout page.

Run from the existing Flask app via:
    from sunday_scout import scout_bp
    app.register_blueprint(scout_bp)

Only pre-kickoff, completed games are used. Historical ranking snapshots are
read-only; the existing watchlist ranking is never changed.
"""

import csv
import io
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import Blueprint, Response, render_template

scout_bp = Blueprint("sunday_scout", __name__)
PROJECT = Path(__file__).resolve().parent
MATCHUPS = PROJECT / "sunday_matchups_2026-10-11.csv"
HISTORY = PROJECT / "nfl_games.csv"
WINDOWS = ("3", "5", "10", "all")


def read_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _team_summary(games):
    if not games:
        return None
    count = len(games)
    recent = games[-3:]
    ats = [g["ats"] for g in games if g["ats"] is not None]
    return {
        "games": count,
        "pf": round(sum(g["pf"] for g in games) / count, 1),
        "pa": round(sum(g["pa"] for g in games) / count, 1),
        "diff": round(sum(g["pf"] - g["pa"] for g in games) / count, 1),
        "wins": sum(g["pf"] > g["pa"] for g in games),
        "losses": sum(g["pf"] < g["pa"] for g in games),
        "ties": sum(g["pf"] == g["pa"] for g in games),
        "ats_w": ats.count("W"),
        "ats_l": ats.count("L"),
        "ats_p": ats.count("P"),
        "ats_known": len(ats),
        "recent_diff": round(sum(g["pf"] - g["pa"] for g in recent) / len(recent), 1),
        "recent_ats": "".join(g["ats"] or "?" for g in recent),
    }


def team_form_for_date(nfl_games, season, before_date):
    """Only final REG games with dates strictly earlier than this matchup.

    ATS convention in nfl_games.csv: a home cover occurs when
    (home_score - away_score) > spread_line.
    """
    by_team = defaultdict(list)
    for g in sorted(nfl_games, key=lambda row: (row.get("gameday", ""), row.get("game_id", ""))):
        if g.get("season") != str(season) or g.get("game_type") != "REG":
            continue
        if not g.get("gameday") or g["gameday"] >= before_date:
            continue
        home = _score(g.get("home_score"))
        away = _score(g.get("away_score"))
        if home is None or away is None:
            continue

        home_ats = away_ats = None
        try:
            line = float(g["spread_line"])
        except (ValueError, KeyError, TypeError):
            pass
        else:
            margin = (home - away) - line
            home_ats = "W" if margin > 1e-8 else "L" if margin < -1e-8 else "P"
            away_ats = "L" if margin > 1e-8 else "W" if margin < -1e-8 else "P"

        by_team[g["home_team"]].append({"pf": home, "pa": away, "ats": home_ats})
        by_team[g["away_team"]].append({"pf": away, "pa": home, "ats": away_ats})

    return {team: _team_summary(games) for team, games in by_team.items()}


def saved_rankings(matchup_date):
    """Optional: add rankings from frozen four-window pregame snapshots."""
    ranks = defaultdict(dict)
    for window in WINDOWS:
        path = PROJECT / f"sunday_pregame_{matchup_date}_{window}.csv"
        if not path.exists():
            continue
        for g in read_csv(path):
            key = (g.get("away_team", ""), g.get("home_team", ""))
            value = str(g.get("rank", "")).strip()
            ranks[key][window] = int(value) if value.isdigit() else None
    return ranks


def scout_report():
    if not MATCHUPS.exists() or not HISTORY.exists():
        missing = [str(p.name) for p in (MATCHUPS, HISTORY) if not p.exists()]
        raise FileNotFoundError("Missing input file(s): " + ", ".join(missing))

    matchups = read_csv(MATCHUPS)
    nfl_games = read_csv(HISTORY)
    cache = {}
    ranks_by_date = {}
    cards = []

    for matchup in matchups:
        date = matchup["gameday"]
        year = date[:4]
        if date not in cache:
            cache[date] = team_form_for_date(nfl_games, year, date)
            ranks_by_date[date] = saved_rankings(date)
        form = cache[date]

        dog = matchup["dog_team"]
        away = matchup["away_team"]
        home = matchup["home_team"]
        if dog not in (away, home):
            raise ValueError(f"Underdog {dog} isn't playing in {away} @ {home}")
        favorite = home if dog == away else away
        dog_form, favorite_form = form.get(dog), form.get(favorite)
        spread = float(matchup["dog_spread"])
        rank_lookup = ranks_by_date[date].get((away, home), {})
        ranks = {window: rank_lookup.get(window) for window in WINDOWS}
        available = [value for value in ranks.values() if value is not None]

        model_dog = model_fav = margin = cover_cushion = None
        lean = "Not enough 2026 games"
        # This is an intentionally simple, UNCALIBRATED points-based baseline.
        if dog_form and favorite_form and min(dog_form["games"], favorite_form["games"]) >= 3:
            model_dog = round((dog_form["pf"] + favorite_form["pa"]) / 2, 1)
            model_fav = round((favorite_form["pf"] + dog_form["pa"]) / 2, 1)
            margin = round(model_dog - model_fav, 1)
            cover_cushion = round(margin + spread, 1)
            if cover_cushion >= 0:
                lean = "Form leans underdog"
            else:
                lean = "Form leans favorite"

        if len(available) == len(WINDOWS):
            rank_range = max(available) - min(available)
            window_note = "Stable ranks" if rank_range <= 2 else "Era-sensitive ranks"
        else:
            rank_range = None
            window_note = "Add 4 pregame snapshots for rank comparison"

        highlight = ""
        if rank_range is not None and rank_range >= 4:
            highlight = "Historical ranking changes across eras"
        elif len(available) == len(WINDOWS) and max(available) <= 4 and cover_cushion is not None:
            if cover_cushion >= 0:
                highlight = "Recent form and historical rankings both favor the underdog"
            else:
                highlight = "Current form conflicts with strong historical ranking"

        cards.append({
            "date": date,
            "kickoff": matchup.get("gametime_et", ""),
            "away": away, "home": home, "dog": dog, "favorite": favorite,
            "dog_location": matchup["dog_location"], "spread": spread,
            "dog_form": dog_form, "favorite_form": favorite_form,
            "dog_projected": model_dog, "favorite_projected": model_fav,
            "model_margin": margin, "cover_cushion": cover_cushion,
            "lean": lean, "ranks": ranks, "rank_range": rank_range,
            "window_note": window_note, "highlight": highlight,
            "location_note": "London — designated home team may not have normal home-field advantage"
                             if (date == "2026-10-11" and (away, home) == ("PHI", "JAX")) else "",
            "spread_source_time": matchup.get("spread_snapshot_et", "Unknown"),
        })

    return sorted(cards, key=lambda row: (row["date"], row["kickoff"], row["away"]))


def export_csv(cards):
    data = io.StringIO()
    columns = [
        "date", "kickoff_et", "away", "home", "underdog", "favorite",
        "spread", "rank_3y", "rank_5y", "rank_10y", "rank_all",
        "dog_games", "dog_pf_per_game", "dog_pa_per_game", "dog_ats_record",
        "favorite_games", "favorite_pf_per_game", "favorite_pa_per_game", "favorite_ats_record",
        "form_projection_dog", "form_projection_favorite", "form_cover_cushion", "form_lean", "note",
    ]
    writer = csv.DictWriter(data, fieldnames=columns)
    writer.writeheader()
    for c in cards:
        dog = c["dog_form"] or {}
        fav = c["favorite_form"] or {}
        record = lambda x: (f'{x["ats_w"]}-{x["ats_l"]}-{x["ats_p"]}' if x else "")
        writer.writerow({
            "date": c["date"], "kickoff_et": c["kickoff"],
            "away": c["away"], "home": c["home"],
            "underdog": c["dog"], "favorite": c["favorite"],
            "spread": c["spread"],
            "rank_3y": c["ranks"]["3"], "rank_5y": c["ranks"]["5"],
            "rank_10y": c["ranks"]["10"], "rank_all": c["ranks"]["all"],
            "dog_games": dog.get("games"), "dog_pf_per_game": dog.get("pf"),
            "dog_pa_per_game": dog.get("pa"), "dog_ats_record": record(dog),
            "favorite_games": fav.get("games"), "favorite_pf_per_game": fav.get("pf"),
            "favorite_pa_per_game": fav.get("pa"), "favorite_ats_record": record(fav),
            "form_projection_dog": c["dog_projected"],
            "form_projection_favorite": c["favorite_projected"],
            "form_cover_cushion": c["cover_cushion"],
            "form_lean": c["lean"],
            "note": c["location_note"],
        })
    return data.getvalue()


@scout_bp.route("/sunday-scout")
def sunday_scout_page():
    from flask import request, current_app, redirect, url_for
    if current_app.config.get('EXPERT_BETA_ENABLED') and request.endpoint=='sunday_scout.sunday_scout_page' and request.args.get('download')!='1':
        return redirect(url_for('plug_page'))
    from scout4.blend import view as blend_view
    all_blends=blend_view()
    from site_week import active_week
    current=active_week(read_csv(HISTORY))
    blends=[r for r in all_blends if (r.get('season'),r.get('week'))==current]
    archived_blends=[r for r in all_blends if r not in blends]

    try:
        cards = scout_report()
    except (FileNotFoundError, ValueError) as error:
        if not blends:
            return f"Sunday Scout setup error: {error}", 500
        cards=[]

    if request.args.get("download") == "1":
        if blends:
            stream=io.StringIO()
            fields=['game_id','kickoff_utc','away_team','home_team','away_handicap','blend_pick','blend_away_margin','blend_ats_edge','total_line','total_pick','estimated_total','sealed_at_utc']
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for r in blends:
                b=r['components']['Blend'];total=r.get('totals')
                writer.writerow({'game_id':r['game_id'],'kickoff_utc':r['kickoff_utc'],'away_team':r['away_team'],'home_team':r['home_team'],'away_handicap':r['quote']['line'],'blend_pick':b['pick'],'blend_away_margin':b['away_margin'],'blend_ats_edge':b['ats_edge'],'total_line':total['quote']['line'] if total else '', 'total_pick':total['prediction']['lean'] if total else '', 'estimated_total':total['prediction']['total'] if total else '', 'sealed_at_utc':r['sealed_at_utc']})
            contents=stream.getvalue()
        else:
            contents = export_csv(cards)
        return Response(
            contents,
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=the_plug_forecasts.csv"},
        )
    return render_template("sunday_scout.html", cards=cards, blends=blends,archived_blends=archived_blends)


