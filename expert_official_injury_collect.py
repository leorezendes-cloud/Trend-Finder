"""Bounded, review-first official NFL injury page retrieval.

Never runs in a web request or scheduler. No writes, paid APIs or bulk downloads.
An operator must verify and save individual game records before Expert uses them.
"""
import argparse
import json
from pathlib import Path
import os
import csv
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag in ("tr", "td", "th", "h1", "h2", "h3", "p"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("tr", "td", "th", "h1", "h2", "h3", "p"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            text = data.strip()
            if text:
                self.parts.append(text + " ")



class _InjuryTableParser(HTMLParser):
    """Extract candidate table rows, never independently verified statuses."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.hidden = 0
        self.heading = None
        self.heading_parts = None
        self.table_heading = None
        self.recent_text = []
        self.table_label = None

    def handle_starttag(self, tag, attrs):
        if tag in ("h2", "h3", "h4"):
            self.heading_parts = []
        if tag == "table":
            self.table_heading = self.heading
            self.table_label = next((v for v in reversed(self.recent_text[-12:])
                                     if v in _NFL_TEAM_LABELS), None)
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in ("script", "style"):
            self.hidden += 1

    def handle_data(self, data):
        if self.heading_parts is not None:
            self.heading_parts.append(data)
        if self.cell is None and self.table is None and not self.hidden:
            cleaned = " ".join(data.split())
            if cleaned:
                self.recent_text.append(cleaned)
                self.recent_text = self.recent_text[-24:]
        if self.cell is not None and not self.hidden:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("h2", "h3", "h4") and self.heading_parts is not None:
            self.heading = " ".join("".join(self.heading_parts).split())[:100]
            self.heading_parts = None
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append((self.table_heading, self.table_label, self.table))
            self.table = None


def injury_table_candidates(html):
    """Read only recognizable 5-column injury tables; no team inference.

    Team identity and report publication date must be verified separately.
    """
    parser = _InjuryTableParser()
    parser.feed(html)
    candidates = []
    for heading, label, table in parser.tables:
        if not table:
            continue
        headers = [column.lower() for column in table[0]]
        expected = ("player", "position", "injuries", "practice status", "game status")
        if len(headers) != 5 or any(word not in header for word, header in zip(expected, headers)):
            continue
        rows = []
        for cells in table[1:]:
            if len(cells) != 5 or not cells[0] or len(cells[0]) > 100:
                continue
            if cells[4] not in ("", "Out", "Doubtful", "Questionable"):
                continue
            rows.append({"name": cells[0], "position": cells[1],
                         "injury": cells[2], "practice_status": cells[3],
                         "game_status": cells[4] or "Not Reported"})
        if rows:
            candidates.append({"verified": False, "team": None,
                               "source_heading": heading,
                               "source_team_label": label,
                               "players": rows[:60]})
    return candidates[:32]



# Explicit NFL page labels; a label is only a candidate, not a verified record.
_NFL_TEAM_LABELS = {
    "Packers": "GB", "Rams": "LA", "Bears": "CHI", "Lions": "DET",
    "Vikings": "MIN", "Cowboys": "DAL", "Giants": "NYG",
    "Eagles": "PHI", "Commanders": "WAS", "49ers": "SF",
    "Seahawks": "SEA", "Cardinals": "ARI", "Falcons": "ATL",
    "Panthers": "CAR", "Saints": "NO", "Buccaneers": "TB",
    "Bills": "BUF", "Dolphins": "MIA", "Patriots": "NE",
    "Jets": "NYJ", "Ravens": "BAL", "Bengals": "CIN",
    "Browns": "CLE", "Steelers": "PIT", "Texans": "HOU",
    "Colts": "IND", "Jaguars": "JAX", "Titans": "TEN",
    "Broncos": "DEN", "Chiefs": "KC", "Raiders": "LV",
    "Chargers": "LAC",
}


def label_team_candidates(candidates):
    """Assign a team only for an exact, unambiguous official table heading.

    The returned team is still unverified, and cannot be imported automatically.
    """
    from collections import Counter
    headings = [item.get("source_team_label") for item in candidates]
    counts = Counter(headings)
    result = []
    for item in candidates:
        entry = dict(item)
        heading = item.get("source_team_label")
        code = _NFL_TEAM_LABELS.get(heading)
        entry["team"] = code if code and counts[heading] == 1 else None
        entry["team_label_confidence"] = (
            "exact_unique_heading" if entry["team"] else "unknown")
        entry["verified"] = False
        result.append(entry)
    return result


def fetch_official_injury_page(season, week, *, opener=None):
    """Fetch a single official week page, max 1 MiB, without persisting anything.

    The page is a research candidate, NOT an independently verified player record.
    """
    if not (2020 <= season <= 2100 and 1 <= week <= 22):
        raise ValueError("Invalid season/week")
    url = f"https://www.nfl.com/injuries/league/{season}/REG{week}"
    if urlsplit(url).hostname != "www.nfl.com":
        raise ValueError("Untrusted host")
    request = Request(url, headers={"User-Agent": "TrendFindahExpertEvidence/1.0",
                                     "Accept": "text/html"})
    client = opener or build_opener(_NoRedirect())
    with client.open(request, timeout=12) as response:
        page_last_modified = response.headers.get("Last-Modified")
        page_date = response.headers.get("Date")
        if response.geturl() != url:
            raise ValueError("Unexpected source redirect")
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            raise ValueError("Unexpected content type")
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Official source exceeds 1 MiB; no data saved")
    html = raw.decode("utf-8", errors="replace")
    parser = _VisibleText()
    parser.feed(html)
    lines = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    lines = [line for line in lines if line]
    if not any(f"WEEK {week}" in line.upper() for line in lines[:100]):
        raise ValueError("Official page does not confirm requested week")
    return {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "season": season, "week": week, "verified_player_records": False,
            "note": "Read-only source preview. Do not treat as verified injury statuses.",
            "preview": lines[:120],
            "http_page_metadata": {"last_modified": page_last_modified, "date": page_date,
                                   "note": "HTTP headers describe the page response, not individual injury-report publication times"},
            "publication_provenance": {
                "published_at": None,
                "status": "not_established_from_week_page",
                "retrieved_at_is_not_publication_time": True,
                "required_before_import": [
                    "independently documented publication timestamp",
                    "exact game_id and kickoff_utc from Scout",
                    "team and player-status review",
                    "published_at <= observed_at < kickoff_utc",
                ],
            },
            "unverified_table_candidates": label_team_candidates(injury_table_candidates(html))}



def preflight_game(snapshot, game, as_of):
    """Read-only exact-game eligibility audit; NEVER verifies or imports players.

    The first observed timestamp proves availability no earlier than that moment.
    HTTP Last-Modified, page headings and retrieval time are not publication dates.
    """
    def stamp(value):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc)

    issues = []
    if not isinstance(snapshot, dict) or not isinstance(game, dict):
        raise ValueError("Expected snapshot and Scout game objects")
    if (snapshot.get("season") != game.get("season")
            or snapshot.get("week") != game.get("week")):
        issues.append("season_week_mismatch")
    game_id = game.get("game_id")
    if not isinstance(game_id, str) or not game_id:
        issues.append("missing_exact_game_id")
    teams = (game.get("away_team"), game.get("home_team"))
    if any(not isinstance(t, str) or not t for t in teams) or teams[0] == teams[1]:
        issues.append("missing_matchup_teams")
    try:
        observed = stamp(snapshot["retrieved_at"])
        kickoff = stamp(game["kickoff_utc"])
        cutoff = stamp(as_of)
        if not observed < kickoff:
            issues.append("observed_at_or_after_kickoff")
        if not observed <= cutoff:
            issues.append("observed_after_analysis_cutoff")
        if not cutoff < kickoff:
            issues.append("analysis_at_or_after_kickoff")
        if observed > datetime.now(timezone.utc):
            issues.append("future_observation")
    except (KeyError, TypeError, ValueError):
        issues.append("missing_or_invalid_timestamps")
    if snapshot.get("verified_player_records") is not False:
        issues.append("unexpected_verified_flag")
    source = snapshot.get("source_url")
    expected_url = (f"https://www.nfl.com/injuries/league/"
                    f"{snapshot.get('season')}/REG{snapshot.get('week')}")
    if source != expected_url:
        issues.append("unexpected_official_source")
    rows = snapshot.get("unverified_table_candidates")
    if not isinstance(rows, list):
        rows = []
        issues.append("missing_candidate_tables")
    matched = {}
    for team in teams:
        candidates = [r for r in rows if isinstance(r, dict) and r.get("team") == team
                      and r.get("team_label_confidence") == "exact_unique_heading"
                      and r.get("verified") is False]
        if len(candidates) != 1:
            issues.append("missing_or_ambiguous_team_" + str(team))
        else:
            matched[team] = len(candidates[0].get("players", []))
            if not 1 <= matched[team] <= 60:
                issues.append("invalid_player_count_" + team)
    return {
        "game_id": game_id, "teams": list(teams),
        "candidate_player_counts": matched,
        "structural_preflight_passed": not issues,
        "issues": issues,
        "eligible_for_automatic_import": False,
        "publication_time_verified": False,
        "review_required": ["independent report publication evidence",
                            "human review of player statuses and exact matchup",
                            "reviewed importer validation"],
        "note": "Observed availability is not the report's original publication timestamp.",
    }


def save_observation(snapshot, destination):
    """Opt-in immutable research capture; never enters Expert verified store."""
    path = Path(destination)
    if path.suffix != ".json" or path.is_symlink():
        raise ValueError("Observation destination must be a new .json file")
    if snapshot.get("verified_player_records") is not False:
        raise ValueError("Only unverified observations may be captured")
    if "game_preflight" not in snapshot:
        raise ValueError("Exact-game preflight required before saving")
    if not snapshot["game_preflight"].get("structural_preflight_passed"):
        raise ValueError("Failed preflight; observation not saved")
    data = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(data) > 131072:
        raise ValueError("Observation exceeds 128 KiB")
    # Exclusive creation prevents silently rewriting the first-observed evidence.
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def scout_game_from_schedule(path, game_id, season, week):
    """Resolve one exact NFLverse Scout schedule row; reject ambiguous or missing times."""
    if not isinstance(game_id, str) or not game_id:
        raise ValueError("Exact game ID required")
    matches = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (row.get("game_id") == game_id and row.get("season") == str(season)
                    and row.get("week") == str(week) and row.get("game_type") == "REG"):
                matches.append(row)
    if len(matches) != 1:
        raise ValueError("Expected exactly one matching regular-season Scout game")
    row = matches[0]
    away, home = row.get("away_team"), row.get("home_team")
    if not away or not home or away == home:
        raise ValueError("Missing distinct matchup teams")
    date, clock = row.get("gameday"), row.get("gametime")
    if not date or not clock:
        raise ValueError("Scout schedule lacks a precise gameday/gametime")
    try:
        local = datetime.fromisoformat(date + "T" + clock)
        if local.tzinfo is not None:
            raise ValueError("Unexpected timezone in Scout gametime")
        kickoff = local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid Scout kickoff: " + str(exc)) from exc
    return {"game_id": game_id, "season": season, "week": week,
            "away_team": away, "home_team": home, "kickoff_utc": kickoff.isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--scout-schedule", help="Existing Scout nfl_games.csv; requires --game-id")
    parser.add_argument("--game-id", help="Exact Scout game ID; requires --scout-schedule")
    parser.add_argument("--game-json", help="Local Scout game JSON with exact game_id, teams, kickoff")
    parser.add_argument("--as-of", help="Expert cutoff ISO timestamp (timezone required)")
    parser.add_argument("--save-observation", help="Save immutable unverified exact-game evidence to a new JSON path")
    parser.add_argument("--compact", action="store_true",
                        help="Show team counts and provenance instead of all player rows")
    args = parser.parse_args()
    if args.game_json and args.scout_schedule:
        parser.error("Choose either --game-json or --scout-schedule")
    if bool(args.scout_schedule) != bool(args.game_id):
        parser.error("--scout-schedule and --game-id are required together")
    if args.save_observation and (not (args.game_json or args.scout_schedule) or not args.as_of):
        parser.error("--save-observation requires --game-json and --as-of")
    if bool(args.game_json or args.scout_schedule) != bool(args.as_of):
        parser.error("--game-json and --as-of must be provided together")
    if args.as_of:
        try:
            cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if cutoff.tzinfo is None:
                raise ValueError("Timezone required")
            if cutoff.astimezone(timezone.utc) > datetime.now(timezone.utc):
                raise ValueError("Cutoff cannot be in the future")
            if args.scout_schedule:
                game = scout_game_from_schedule(args.scout_schedule, args.game_id, args.season, args.week)
            else:
                game = json.loads(Path(args.game_json).read_text(encoding="utf-8"))
                if isinstance(game, dict) and isinstance(game.get("game"), dict):
                    game = game["game"]
        except (OSError, ValueError, TypeError) as exc:
            parser.error("Invalid game JSON or as-of: " + str(exc))
        if not isinstance(game, dict):
            parser.error("Game JSON must contain a game object")
        if game.get("season") != args.season or game.get("week") != args.week:
            parser.error("Game season/week differs from requested source")
    snapshot = fetch_official_injury_page(args.season, args.week)
    if args.game_json or args.scout_schedule:
        audit = preflight_game(snapshot, game, args.as_of)
        snapshot["game_preflight"] = audit
    if args.save_observation:
        # Store the complete candidate rows before compact output removes them.
        save_observation(snapshot, args.save_observation)
    if args.compact:
        snapshot.pop("preview", None)
        snapshot["candidate_summary"] = [
            {"team": r.get("team"), "source_team_label": r.get("source_team_label"),
             "player_count": len(r.get("players", [])),
             "team_label_confidence": r.get("team_label_confidence")}
            for r in snapshot.pop("unverified_table_candidates", [])]
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
