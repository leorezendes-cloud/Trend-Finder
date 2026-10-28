"""Independent 2026 NFL Vegas-total reconstruction, frozen v14 feature schema.

The model trains only on previous seasons' recorded market totals. Its target
game's market total is not a feature; the selection policy may compare after
the independent projection is computed. Features are pre-week snapshots.
"""
import math
from pathlib import Path
import plug_v14_baseline as base
import plug_v14_qb as qb

VERSION='independent-vegas-v14-2026'

def projections(games_file,*,season=2026,eligible_ids=None):
    if season!=2026:
        raise ValueError('Frozen v14 release supports 2026 only')
    games_file=Path(games_file)
    games=base.load_games(games_file)
    qb.attach_qb_ids(games,qb.read_qb_ids(games_file))
    rows=base.build_v2(games)
    prior,_=qb.prior_qb_features(games)
    recent,_=qb.v10_qb_features(games)
    prepared=[]
    for game,features in rows:
        hist=prior[game['id']]
        rec=recent[game['id']]
        # Exact 14-feature v14 recipe: 11 v2 features + recent QB
        # offensive residual + older QB continuity and experience.
        # The recent QB game-total residual is deliberately excluded.
        x=features+[rec[0],hist[2],hist[3]]
        if len(x)!=14:raise RuntimeError('Frozen v14 schema mismatch')
        prepared.append((game,x))
    training=[(x,g['market']) for g,x in prepared
              if base.TRAIN_START<=g['year']<season and base.is_complete(g)
              and not base.latest_season_week(g['year'],g['week'])]
    coeff=base.fit(training)
    out={}
    for g,x in prepared:
        if g['year']!=season or (eligible_ids is not None and g['id'] not in eligible_ids):
            continue
        estimate=sum(a*b for a,b in zip(coeff,x))
        if not math.isfinite(estimate) or not 10<estimate<90:
            raise RuntimeError('Invalid independent v14 total '+g['id'])
        out[g['id']]=estimate
    return out
