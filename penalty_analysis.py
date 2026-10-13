"""High-penalty games with referee context from prior observations only."""
import csv,math

def penalty_events(root,games,year):
    path=root/'game_penalty_stats.csv';rows=[]
    assignments={}
    assignment_path=root/'referee_assignments.csv'
    if assignment_path.exists():
        with assignment_path.open(newline='') as f:
            assignments={r['game_id']:r for r in csv.DictReader(f)}
    if not path.exists():return []
    with path.open(newline='') as f:
        for raw in csv.DictReader(f):
            game=games.get(raw['game_id'])
            if not game or not game.get('away_score') or not game.get('home_score'):continue
            try:values=[int(raw[key]) for key in ['away_penalties','home_penalties','away_penalty_yards','home_penalty_yards']]
            except (ValueError,KeyError):continue
            if min(values)<0:continue
            rows.append(dict(raw,game=game,count=values[0]+values[1],yards=values[2]+values[3],away_count=values[0],home_count=values[1],referee=(game.get('referee') or assignments.get(raw['game_id'],{}).get('referee') or 'Unknown').strip(),referee_source=assignments.get(raw['game_id'],{}).get('source_url','') if not game.get('referee') else ''))
    events=[]
    for row in rows:
        game=row['game']
        if year!='all' and game['season']!=str(year):continue
        prior=[p for p in rows if p['game']['gameday']<game['gameday'] and int(p['game']['season'])>=int(game['season'])-3]
        if len(prior)<100:continue
        counts=sorted(p['count'] for p in prior);cutoff=counts[math.ceil(.95*len(counts))-1]
        if row['count']<cutoff:continue
        league_mean=sum(p['count'] for p in prior)/len(prior)
        crew=[p for p in prior if row['referee']!='Unknown' and p['referee']==row['referee']]
        ref_mean=sum(p['count'] for p in crew)/len(crew) if crew else None
        ref_high=sum(p['count']>=cutoff for p in crew)
        league_high=sum(p['count']>=cutoff for p in prior)
        events.append(dict(ref_high=ref_high,ref_high_rate=round(100*ref_high/len(crew),1) if crew else None,league_high_rate=round(100*league_high/len(prior),1),event_id=game['game_id']+'penalties',category='game',event_date=game['gameday'],title='High Penalty Count',status='Calculated',team='',player='',game_id=game['game_id'],matchup=f"{game['away_team']} @ {game['home_team']}",description=f"{row['count']} penalties for {row['yards']} yards; prior-game 95th-percentile cutoff: {cutoff} penalties.",source_url=row['source_url'],penalty=row,referee=row['referee'],ref_games=len(crew),ref_mean=round(ref_mean,1) if ref_mean is not None else None,league_mean=round(league_mean,1),league_games=len(prior),ref_difference=round(ref_mean-league_mean,1) if ref_mean is not None else None,ref_context='Higher prior penalty average' if ref_mean is not None and len(crew)>=5 and ref_mean>=league_mean+2 else 'Lower prior penalty average' if ref_mean is not None and len(crew)>=5 and ref_mean<=league_mean-2 else 'No large average difference' if len(crew)>=5 else 'Limited referee sample'))
    return events
