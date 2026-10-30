"""Offline selected-column aggregation. Polars is optional; never imported by readers."""
import json
from .store import sha, timestamp, team

COLUMNS=['game_id','season','week','posteam','defteam','play_type','qb_dropback','epa',
         'wp','qtr','sack','qb_hit','passer_player_id','cpoe','rush_attempt']

def ingest_pbp(db,path,*,season,captured_at,url):
    import polars as pl
    checksum=sha(path);captured=timestamp(captured_at)
    prior=db.execute('SELECT sha FROM sources WHERE kind=? AND season=?',('pbp',season)).fetchone()
    if prior and prior[0]==checksum:return {'unchanged':True,'sha256':checksum}
    scan=pl.scan_parquet(path)
    if not set(COLUMNS+['play_id'])<=set(scan.collect_schema().names()):raise ValueError('PBP schema missing required fields')
    scan=scan.select(COLUMNS+['play_id']).filter((pl.col('season')==season)&pl.col('play_type').is_in(['pass','run']) &
        (pl.col('wp')>=.2)&(pl.col('wp')<=.8)&(pl.col('qtr')<=3)&pl.col('epa').is_not_null())
    if scan.filter(~pl.col('epa').is_finite() | (pl.col('cpoe').is_not_null() & ~pl.col('cpoe').is_finite())).limit(1).collect(engine='streaming').height:
        raise ValueError('Non-finite PBP statistic')
    if scan.group_by(['game_id','play_id']).len().filter(pl.col('len')>1).limit(1).collect(engine='streaming').height:
        raise ValueError('Duplicate PBP play identity')
    drop=pl.col('qb_dropback')==1
    expr=[pl.len().alias('plays'),drop.sum().alias('dropbacks'),
          pl.when(drop).then(pl.col('epa')).otherwise(0).sum().alias('pass_epa'),
          (~drop).sum().alias('runs'),pl.when(~drop).then(pl.col('epa')).otherwise(0).sum().alias('rush_epa'),
          pl.when(drop).then(pl.col('sack').fill_null(0)).otherwise(0).sum().alias('sacks'),
          pl.when(drop).then(pl.col('qb_hit').fill_null(0)).otherwise(0).sum().alias('hits'),
          (drop & (pl.col('qb_hit')==1)).sum().alias('hit_dropbacks'),
          pl.when(drop & (pl.col('qb_hit')==1)).then(pl.col('epa')).otherwise(0).sum().alias('hit_epa'),
          pl.col('cpoe').sum().alias('cpoe_sum'),pl.col('cpoe').count().alias('cpoe_n')]
    # Only a few thousand aggregate rows are materialized. No full PBP to Python.
    grouped=scan.group_by(['game_id','posteam','defteam']).agg(expr).collect(engine='streaming')
    qb=scan.filter(drop & pl.col('passer_player_id').is_not_null()).group_by(
        ['game_id','posteam','defteam','passer_player_id']).agg(expr).collect(engine='streaming')
    count=0
    with db:
        db.execute("DELETE FROM observations WHERE kind='pbp' AND gid IN (SELECT gid FROM games WHERE season=?)",(season,))
        for frame,is_qb in ((grouped,False),(qb,True)):
            for row in frame.iter_rows(named=True):
                gid=row.pop('game_id');t=team(row.pop('posteam'));o=team(row.pop('defteam'))
                pid=row.pop('passer_player_id') if is_qb else ''
                g=db.execute('SELECT away,home FROM games WHERE gid=?',(gid,)).fetchone()
                if g is None:continue
                if {t,o}!=set(g):raise ValueError('PBP schedule mismatch')
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',('pbp',gid,t,o,pid,'QB' if is_qb else '', '',captured,json.dumps(row,separators=(',',':'))));count+=1
        if not count:raise ValueError('No eligible PBP summaries')
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',('pbp',season,checksum,url,captured,count))
    return {'unchanged':False,'rows':count,'sha256':checksum}

def ingest_charting(db,path,pbp_path,*,season,captured_at,url):
    """Verified historical participation join. No extrapolation to current season.

    Counts five-plus rushers, not an invented blitz designation. Pressure and
    man/zone require provider fields; source availability still gates every row.
    """
    import polars as pl
    from .store import sha
    checksum=sha(path)+':'+sha(pbp_path);captured=timestamp(captured_at)
    prior=db.execute("SELECT sha FROM sources WHERE kind='charting' AND season=?",(season,)).fetchone()
    if prior and prior[0]==checksum:return {'unchanged':True,'sha256_pair':checksum}
    scan=pl.scan_parquet(path)
    fields=['nflverse_game_id','play_id','number_of_pass_rushers','was_pressure','defense_man_zone_type']
    if not set(fields)<=set(scan.collect_schema().names()):raise ValueError('Required charting unavailable')
    chart=scan.select(fields).rename({'nflverse_game_id':'game_id'}).with_columns(
        pl.col('play_id').cast(pl.Int64),
        pl.col('defense_man_zone_type').replace({'MAN_COVERAGE':'MAN','ZONE_COVERAGE':'ZONE'}))
    # Reject ambiguous keys rather than multiply observations on join.
    dup=chart.group_by(['game_id','play_id']).len().filter(pl.col('len')>1).limit(1).collect(engine='streaming')
    if dup.height:raise ValueError('Duplicate charting play identity')
    pb=pl.scan_parquet(pbp_path).select(COLUMNS+['play_id']).filter((pl.col('season')==season)&(pl.col('qb_dropback')==1)&pl.col('epa').is_not_null())
    pb=pb.with_columns(pl.col('play_id').cast(pl.Int64))
    joined=pb.join(chart,on=['game_id','play_id'],how='inner',validate='1:1')
    pressure=pl.col('was_pressure')==True
    sums=[pl.len().alias('joined_dropbacks'),pl.col('was_pressure').count().alias('pressure_known'),
          pressure.sum().alias('pressure_n'),pl.when(pressure).then(pl.col('epa')).otherwise(0).sum().alias('pressure_epa'),
          pl.col('number_of_pass_rushers').count().alias('rushers_known'),(pl.col('number_of_pass_rushers')>=5).sum().alias('five_plus_rushers'),
          pl.col('defense_man_zone_type').is_in(['MAN','ZONE']).sum().alias('coverage_known'),
          (pl.col('defense_man_zone_type')=='MAN').sum().alias('man_n')]
    frames=[(joined.group_by(['game_id','posteam','defteam']).agg(sums).collect(engine='streaming'),False),
            (joined.filter(pl.col('passer_player_id').is_not_null()).group_by(['game_id','posteam','defteam','passer_player_id']).agg(sums).collect(engine='streaming'),True)]
    count=0
    with db:
        db.execute("DELETE FROM observations WHERE kind='charting' AND gid IN (SELECT gid FROM games WHERE season=?)",(season,))
        for frame,isqb in frames:
            for row in frame.iter_rows(named=True):
                gid=row.pop('game_id');t=team(row.pop('posteam'));o=team(row.pop('defteam'));pid=row.pop('passer_player_id') if isqb else ''
                g=db.execute('SELECT away,home FROM games WHERE gid=?',(gid,)).fetchone()
                if g is None:continue
                if {t,o}!=set(g):raise ValueError('Charting schedule mismatch')
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',('charting',gid,t,o,pid,'QB' if isqb else '', '',captured,json.dumps(row,separators=(',',':'))));count+=1
        if not count:raise ValueError('No charting rows joined')
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',('charting',season,checksum,url,captured,count))
    return {'unchanged':False,'rows':count,'sha256_pair':checksum}
