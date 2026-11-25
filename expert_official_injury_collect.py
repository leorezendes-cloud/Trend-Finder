"""Bounded, review-first official NFL injury page retrieval.

Never runs in a web request or scheduler. No writes, paid APIs or bulk downloads.
An operator must verify and save individual game records before Expert uses them.
"""
import argparse
import json
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
        if response.geturl() != url:
            raise ValueError("Unexpected source redirect")
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            raise ValueError("Unexpected content type")
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Official source exceeds 1 MiB; no data saved")
    parser = _VisibleText()
    parser.feed(raw.decode("utf-8", errors="replace"))
    lines = [" ".join(part.split()) for part in "".join(parser.parts).splitlines()]
    lines = [line for line in lines if line]
    if not any(f"WEEK {week}" in line.upper() for line in lines[:100]):
        raise ValueError("Official page does not confirm requested week")
    return {"source_url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "season": season, "week": week, "verified_player_records": False,
            "note": "Read-only source preview. Do not treat as verified injury statuses.",
            "preview": lines[:120]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(fetch_official_injury_page(args.season, args.week), indent=2))


if __name__ == "__main__":
    main()
