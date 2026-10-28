"""Select every independent v14 O/U signal meeting approved eligibility.

No arbitrary quota or top-quarter restriction. Original Scout and Plug v1
directions remain immutable; the weekly v3 file records selection membership.
"""
import math
POLICY_VERSION='plug-ou-all-qualified-v3'

def shortlist(rows):
    seen=set()
    selected=set()
    for row in rows:
        key=(int(row['season']),int(row['week']),row['game_id'])
        if key in seen:
            raise ValueError('Duplicate Plug O/U candidate')
        seen.add(key)
        gap=float(row['gap'])
        if not math.isfinite(gap):
            raise ValueError('Nonfinite independent O/U gap')
        if bool(row.get('eligible', True)) and abs(gap)>1e-9:
            selected.add(row['game_id'])
    return selected
