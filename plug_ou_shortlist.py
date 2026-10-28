"""Prospective Plug totals shortlist: rank independently issued v14 signals.

This is a new policy version. Existing v1 side-only receipts remain untouched.
The top quarter is a selection-budget rule, not a claim of calibrated value.
"""
import math
from collections import defaultdict

POLICY_VERSION='plug-ou-top-quarter-v2'

def shortlist(rows):
    """Rank nonzero independent market-v14 gaps within each season/week.

    Deterministic ties use game_id. This policy selects at most ceil(N/4)
    per complete weekly slate; N counts eligible nonzero v14 gaps. It never
    retroactively selects already-started games.
    """
    groups=defaultdict(list)
    seen=set()
    for row in rows:
        game_id=row['game_id']
        key=(int(row['season']),int(row['week']),game_id)
        if key in seen:raise ValueError('Duplicate Plug O/U candidate')
        seen.add(key)
        gap=float(row['gap'])
        if not math.isfinite(gap):raise ValueError('Nonfinite independent O/U gap')
        if abs(gap)>1e-9:
            groups[key[:2]].append(row)
    chosen=set()
    for group in groups.values():
        ordered=sorted(group,key=lambda r:(-abs(float(r['gap'])),r['game_id']))
        chosen.update(r['game_id'] for r in ordered[:math.ceil(len(ordered)/4)])
    return chosen
