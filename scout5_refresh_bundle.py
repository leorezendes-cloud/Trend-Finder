"""Update only Scout 5.0 weekly EPA snapshots from the SAME SportsDataverse release.

Runs off-host (GitHub Actions), so Render never needs DuckDB or PyArrow.
No fallback ratings, coefficient refits, replay rewriting, or ATS changes.
"""
import argparse
import json
import math
import os
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

from scout5_totals import ALIAS, load_bundle

URL = ("https://github.com/sportsdataverse/sportsdataverse-data/"
       "releases/download/nfl_ratings_weekly/nfl_ratings_weekly_2026.parquet")
REQUIRED = {"season", "team_id", "as_of_week", "games", "adj_off_epa",
            "adj_def_epa", "adj_net"}


def collect(rows, season):
    groups = defaultdict(dict)
    for row in rows:
        if int(row["season"]) != season:
            raise ValueError("Unexpected ratings season")
        week = int(row["as_of_week"])
        games = int(row["games"])
        team = ALIAS.get(str(row["team_id"]), str(row["team_id"]))
        off, defense, net = (float(row[k]) for k in
                             ("adj_off_epa", "adj_def_epa", "adj_net"))
        if not 2 <= week <= 23 or not 0 <= games <= 23:
            raise ValueError("Out-of-range ratings week or games")
        if not all(math.isfinite(x) for x in (off, defense, net)):
            raise ValueError("Invalid EPA value")
        if abs(off - defense - net) > 1e-6:
            raise ValueError("Ratings net/offense/defense mismatch")
        if team in groups[week]:
            raise ValueError(f"Duplicate team in week {week}: {team}")
        groups[week][team] = [off, defense]
    if not groups or any(len(teams) != 32 for teams in groups.values()):
        raise ValueError("Incomplete week: exactly 32 teams required")
    weeks = sorted(groups)
    if weeks != list(range(2, weeks[-1] + 1)):
        raise ValueError("Missing intermediate weekly rating snapshots")
    return {str(w): groups[w] for w in weeks}


def extend_bundle(bundle, fresh):
    old = bundle["ratings"]
    if sorted(map(int, old)) != list(range(2, max(map(int, old)) + 1)):
        raise ValueError("Existing bundle has missing ratings weeks")
    if max(map(int, fresh)) < max(map(int, old)):
        raise ValueError("Remote ratings are older than deployed bundle")
    # Existing weeks must remain EXACTLY unchanged. Provider corrections
    # require a separate, reviewed migration of the frozen historical cohort.
    for week, teams in old.items():
        if week not in fresh or set(teams) != set(fresh[week]):
            raise ValueError(f"Provider changed/removed week {week}")
        for team, values in teams.items():
            if any(abs(float(a) - float(b)) > 1e-12
                   for a, b in zip(values, fresh[week][team])):
                raise ValueError(f"Provider changed historical rating: W{week} {team}")
    newer = {week: fresh[week] for week in fresh if week not in old}
    if not newer:
        return None
    result = dict(bundle)
    result["ratings"] = {**old, **newer}
    result["ratings_latest_week"] = max(map(int, result["ratings"]))
    # Never change training weights, model metadata, or retrospective 44-26.
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path,
                        default=Path(__file__).with_name("scout5_ou_bundle.json"))
    args = parser.parse_args()
    bundle = load_bundle(args.bundle)
    import pyarrow.parquet as parquet
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "ratings.parquet"
        req = urllib.request.Request(URL, headers={"User-Agent": "TrendFindah-Scout5-Refresh/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response, source.open("wb") as output:
            import shutil
            shutil.copyfileobj(response, output)
        table = parquet.read_table(source)
        if not REQUIRED.issubset(table.column_names):
            raise ValueError("SportsDataverse ratings schema changed")
        fresh = collect(table.to_pylist(), int(bundle["season"]))
    changed = extend_bundle(bundle, fresh)
    if changed is None:
        print("UNCHANGED: SportsDataverse has no newer complete rating week")
        return
    encoded = json.dumps(changed, separators=(",", ":"), allow_nan=False) + "\n"
    # Validate the entire artifact before replacing it.
    with tempfile.NamedTemporaryFile(mode="w", dir=args.bundle.parent,
                                     prefix=".scout5-refresh-", suffix=".json",
                                     delete=False) as out:
        tmp = Path(out.name)
        out.write(encoded)
    try:
        validated = load_bundle(tmp)
        if (validated["coef"] != bundle["coef"]
                or validated["replay_history"] != bundle["replay_history"]):
            raise ValueError("Refresh modified frozen model/replay")
        os.replace(tmp, args.bundle)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"UPDATED: Scout 5.0 ratings now include week {changed['ratings_latest_week']}; "
          "coefficients and replay unchanged")


if __name__ == "__main__":
    main()
