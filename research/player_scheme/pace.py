"""Compact offline pace aggregates; neutral clock cadence is a proxy, not tracking data."""
import json
from pathlib import Path
from .store import sha,timestamp,team,history

COLUMNS=['game_id','season','play_id','posteam','defteam','play_type','fixed_drive','qtr',
 'game_seconds_remaining','half_seconds_remaining','wp','timeout','incomplete_pass','qb_kneel','qb_spike','desc']

def summarize(scan,season):
    import polars as pl
    if not set(COLUMNS)<=set(scan.collect_schema().names()):raise ValueError('Pace columns unavailable')
    q=scan.select(COLUMNS).filter(pl.col('season')==season).sort(['game_id','play_id'])
    if q.group_by(['game_id','play_id']).len().filter(pl.col('len')>1).limit(1).collect(engine='streaming').height:raise ValueError('Duplicate pace play identity')
    # Lead on ALL events, before filtering: timeout/penalty/stoppage rows break pairs.
    leads=['posteam','play_type','fixed_drive','qtr','game_seconds_remaining','half_seconds_remaining','wp','timeout','qb_kneel','qb_spike']
    q=q.with_columns([pl.col(k).shift(-1).over('game_id').alias('next_'+k) for k in leads])
    snap=pl.col('play_type').is_in(['pass','run']) & (pl.col('qb_kneel').fill_null(0)==0)&(pl.col('qb_spike').fill_null(0)==0)
    gap=pl.col('game_seconds_remaining')-pl.col('next_game_seconds_remaining')
    pair=(snap & pl.col('next_play_type').is_in(['pass','run']) &
        (pl.col('posteam')==pl.col('next_posteam')) & (pl.col('fixed_drive')==pl.col('next_fixed_drive')) &
        (pl.col('qtr')==pl.col('next_qtr')) & (pl.col('qtr')<=3) &
        pl.col('wp').is_between(.2,.8) & pl.col('next_wp').is_between(.2,.8) &
        (pl.col('half_seconds_remaining')>120)&(pl.col('next_half_seconds_remaining')>120)&
        (pl.col('timeout').fill_null(0)==0)&(pl.col('next_timeout').fill_null(0)==0)&
        (pl.col('incomplete_pass').fill_null(0)==0)&
        (pl.col('next_qb_kneel').fill_null(0)==0)&(pl.col('next_qb_spike').fill_null(0)==0)&
        ~pl.col('desc').fill_null('').str.to_lowercase().str.contains('out of bounds') & gap.is_between(1,60))
    q=q.with_columns(pair.fill_null(False).alias('pair'),gap.alias('gap'),snap.alias('snap'))
    return q.filter(pl.col('posteam').is_not_null() & pl.col('qtr').is_between(1,4)).group_by(['game_id','posteam','defteam']).agg(
        pl.col('fixed_drive').filter(pl.col('snap') & pl.col('fixed_drive').is_not_null()).n_unique().alias('drives'),
        pl.col('snap').sum().alias('snaps'),pl.col('pair').sum().alias('neutral_pairs'),
        pl.when(pl.col('pair')).then(pl.col('gap')).otherwise(0).sum().alias('neutral_clock_seconds')).collect(engine='streaming')

def ingest_pace(db,path,*,season,captured_at,url):
    import polars as pl
    checksum='pace-v2:'+sha(path);captured=timestamp(captured_at)
    old=db.execute("SELECT sha FROM sources WHERE kind='pace' AND season=?",(season,)).fetchone()
    if old and old[0]==checksum:return {'unchanged':True,'sha256':checksum}
    frame=summarize(pl.scan_parquet(path),season);count=0
    with db:
        db.execute("DELETE FROM observations WHERE kind='pace' AND gid IN (SELECT gid FROM games WHERE season=?)",(season,))
        for r in frame.iter_rows(named=True):
            gid=r.pop('game_id');t=team(r.pop('posteam'));o=team(r.pop('defteam'))
            g=db.execute('SELECT away,home FROM games WHERE gid=?',(gid,)).fetchone()
            if g is None:continue
            if {t,o}!=set(g):raise ValueError('Pace team mismatch')
            if r['drives']<=0 or r['snaps']<=0:continue
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?)',('pace',gid,t,o,'','','',captured,json.dumps(r,separators=(',',':'))));count+=1
        if not count:raise ValueError('No pace rows')
        db.execute('INSERT OR REPLACE INTO sources VALUES(?,?,?,?,?,?)',('pace',season,checksum,url,captured,count))
    return {'unchanged':False,'rows':count,'sha256':checksum}

def estimate(db,away,home,cutoff):
    rows=list(history(db,cutoff,mode='retrospective',kinds=('pace',)))
    if not rows:return None
    pairs=sum(r['values']['neutral_pairs'] for r in rows)
    if not pairs:return None
    league_seconds=sum(r['values']['neutral_clock_seconds'] for r in rows)/pairs
    league_drives=sum(r['values']['drives'] for r in rows)/len(rows)
    league_snaps=sum(r['values']['snaps'] for r in rows)/len(rows)
    result=[]
    for t,o in ((away,home),(home,away)):
        own=[r for r in rows if r['team']==t];oppdef=[r for r in rows if r['opponent']==o]
        n=sum(r['values']['neutral_pairs'] for r in own)
        if len(own)<3 or len(oppdef)<3 or n<20:return None
        seconds=(sum(r['values']['neutral_clock_seconds'] for r in own)+60*league_seconds)/(n+60)
        off=(sum(r['values']['drives'] for r in own)+4*league_drives)/(len(own)+4)
        allowed=(sum(r['values']['drives'] for r in oppdef)+4*league_drives)/(len(oppdef)+4)
        baseline_drives=(off+allowed)/2
        baseline_snaps=((sum(r['values']['snaps'] for r in own)+4*league_snaps)/(len(own)+4)+(sum(r['values']['snaps'] for r in oppdef)+4*league_snaps)/(len(oppdef)+4))/2
        result.append({'team':t,'neutral_seconds':seconds,'pairs':n,'baseline_drives':baseline_drives,'baseline_snaps':baseline_snaps})
    joint_seconds=sum(r['neutral_seconds'] for r in result)/2
    raw_expected=league_drives*league_seconds/joint_seconds
    for r in result:
        r['raw_expected_drives']=raw_expected
        r['ratio']=max(.85,min(1.15,raw_expected/r['baseline_drives']))
        r['expected_drives']=r['baseline_drives']*r['ratio']
        r['expected_snaps']=r['baseline_snaps']*r['ratio']
    return {'teams':result,'league_neutral_seconds':league_seconds,'league_drives':league_drives}
