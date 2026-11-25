"""Import a manually verified official injury report into compact Expert evidence.

This intentionally does not infer player statuses from scraped HTML. It requires
a reviewer-supplied JSON record with provenance and writes one bounded file.
"""
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate(record):
    if not isinstance(record, dict):
        raise ValueError("Expected a JSON object")
    season, week = record.get("season"), record.get("week")
    if type(season) is not int or not 2020 <= season <= 2100:
        raise ValueError("Invalid season")
    if type(week) is not int or not 1 <= week <= 22:
        raise ValueError("Invalid week")
    game_id, team = record.get("game_id"), record.get("team")
    if not isinstance(game_id, str) or not 3 <= len(game_id) <= 80:
        raise ValueError("Missing game ID")
    if not isinstance(team, str) or not (2 <= len(team) <= 3 and team.isalpha() and team.isupper()):
        raise ValueError("Invalid team code")
    url = record.get("source_url")
    if not isinstance(url, str):
        raise ValueError("Missing source URL")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port:
        raise ValueError("Invalid official URL")
    host = (parts.hostname or "").lower()
    if not (host == "nfl.com" or host.endswith(".nfl.com")
            or host in {"packers.com", "www.packers.com",
                        "therams.com", "www.therams.com"}):
        raise ValueError("Unrecognized official source")
    published = _timestamp(record.get("published_at"))
    observed = _timestamp(record.get("observed_at"))
    kickoff = _timestamp(record.get("kickoff_utc"))
    if not published <= observed < kickoff:
        raise ValueError("Report must be published and observed before kickoff")
    if observed > datetime.now(timezone.utc):
        raise ValueError("Observation cannot be in the future")
    players = record.get("players")
    if not isinstance(players, list) or not 1 <= len(players) <= 60:
        raise ValueError("Expected 1-60 verified player entries")
    allowed = {"Out", "Doubtful", "Questionable", "None", "Not Reported"}
    clean = []
    for row in players:
        if not isinstance(row, dict):
            raise ValueError("Invalid player")
        name, status = row.get("name"), row.get("game_status")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            raise ValueError("Missing player name")
        if status not in allowed:
            raise ValueError("Unverified game status; use explicit None/Not Reported if absent")
        fields = {key: row.get(key) for key in (
            "name", "position", "practice_status", "game_status", "injury")}
        if any(value is not None and (not isinstance(value, str) or len(value) > 120)
               for value in fields.values()):
            raise ValueError("Invalid player field")
        clean.append(fields)
    result = {key: record[key] for key in (
        "season", "week", "game_id", "team", "source_url", "published_at", "observed_at")}
    result["players"] = clean
    if len(json.dumps(result).encode("utf-8")) > 32768:
        raise ValueError("Compact evidence exceeds 32 KiB")
    return result


def import_verified(record, root):
    clean = validate(record)
    directory = Path(root) / "data" / "expert_official_injuries" / str(clean["season"])
    directory.mkdir(parents=True, exist_ok=True)
    filename = f'{clean["week"]:02d}-{clean["team"]}-{clean["game_id"]}.json'
    # Game IDs can contain separators; avoid path traversal.
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", clean["game_id"]):
        raise ValueError("Unsafe game ID")
    destination = directory / filename
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if _timestamp(existing["observed_at"]) >= _timestamp(clean["observed_at"]):
            raise ValueError("Existing report is as recent or newer")
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".injury-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(clean, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verified-json", required=True,
                        help="Operator-reviewed record, never raw page HTML")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    record = json.loads(Path(args.verified_json).read_text(encoding="utf-8"))
    print(import_verified(record, args.root))


if __name__ == "__main__":
    main()
