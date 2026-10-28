"""Research-only NFL totals overlay. Requires an independently sealed, same-game v14 projection and saved market line. Do not alter published forecasts."""
import math
POLICY_VERSION = 'plug-totals-48-gap1-v1'

def select(original_side, market_total=None, v14_total=None):
    if original_side not in ('Over', 'Under'): raise ValueError('invalid original side')
    result = dict(policy_version=POLICY_VERSION, side=original_side, original_side=original_side, source='original_plug', gap=None)
    if market_total is None or v14_total is None: return result
    for name, value in (('market_total', market_total), ('v14_total', v14_total)):
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not 10 < value < 90: raise ValueError('invalid ' + name)
    if market_total < 48: return result
    gap = v14_total - market_total
    result["gap"] = round(gap, 6)
    if abs(gap) <= 1e-9: return result
    side = 'Over' if gap > 0 else 'Under'
    if abs(gap) >= 1: side = "Under" if gap > 0 else "Over"
    result.update(side=side, source="follow_v14" if abs(gap) < 1 else "fade_v14")
    return result
