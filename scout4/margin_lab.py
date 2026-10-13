"""Direct-margin research candidate. Never replaces the active scoring model.

One structural experiment: fit scoring difference directly rather than obtaining
it by subtracting independent team-score estimates. All settings are fixed and
2025 remains development evidence. Existing total estimates are not refitted.
"""
import math
from .ratings import build_ratings, solve, PRIOR_GAMES, RIDGE, MIN_GAMES
from .stats import eligible, team_code

VERSION = 'scout4-direct-margin-1'
COLUMNS = ('scoring_strength_diff','recent_margin_diff','venue_scoring_diff',
           'venue_indicator','passing_matchup_diff','rushing_matchup_diff')
LABELS = {'scoring_strength_diff':'Adjusted scoring strength difference',
          'recent_margin_diff':'Recent scoring margin difference',
          'venue_scoring_diff':'Venue scoring context difference',
          'venue_indicator':'Home / away / neutral context',
          'passing_matchup_diff':'Passing offense versus defense difference',
          'rushing_matchup_diff':'Rushing offense versus defense difference'}


def difference(own, other, venue):
    other_venue = {'Home':'Away','Away':'Home','Neutral':'Neutral'}[venue]
    def epa(kind):
        values=(own[f'off_{kind}'],own[f'def_{kind}'],other[f'off_{kind}'],other[f'def_{kind}'])
        if any(value is None for value in values):
            return None
        return own[f'off_{kind}']-other[f'def_{kind}']-other[f'off_{kind}']+own[f'def_{kind}']
    return {'scoring_strength_diff':own['off_scoring']+own['def_scoring']-other['off_scoring']-other['def_scoring'],
            'recent_margin_diff':own['recent_net']-other['recent_net'],
            'venue_scoring_diff':own['venues'][venue]['scoring_context']-other['venues'][other_venue]['scoring_context'],
            'venue_indicator':{'Home':1.0,'Away':-1.0,'Neutral':0.0}[venue],
            'passing_matchup_diff':epa('pass'),'rushing_matchup_diff':epa('rush')}


def build_features(schedule,feed,season):
    output=[]
    for week in range(5,19):
        ratings,_=build_ratings(schedule,feed,season,week)
        for game in schedule:
            if str(game['season'])!=str(season) or game['game_type']!='REG' or int(game['week'])!=week:
                continue
            away,home=team_code(game['away_team']),team_code(game['home_team'])
            if away not in ratings or home not in ratings or min(ratings[away]['games'],ratings[home]['games'])<MIN_GAMES:
                continue
            venue='Neutral' if game.get('location')=='Neutral' else 'Away'
            values=difference(ratings[away],ratings[home],venue)
            if any(value is None or not math.isfinite(value) for value in values.values()):
                continue
            output.append({'game_id':game['game_id'],'season':season,'week':week,'features':values,
                           'history_away':ratings[away]['history_game_ids'],
                           'history_home':ratings[home]['history_game_ids']})
    return output


def labeled_samples(feature_rows,schedule):
    """Attach labels only to features already constructed without target results."""
    lookup={g['game_id']:g for g in schedule}
    return [(row['features'],float(lookup[row['game_id']]['away_score'])-float(lookup[row['game_id']]['home_score']))
            for row in feature_rows if eligible(lookup[row['game_id']],row['season'],19)]


def fit_margin(samples):
    if len(samples)<75:
        raise ValueError('Need 75 completed historical games for this experiment')
    # Zero-centered differences and a zero intercept enforce side-swap symmetry.
    # Home advantage is fitted through the explicit venue indicator; neutral = 0.
    scales=[max(1e-6,math.sqrt(sum(x[c]**2 for x,y in samples)/len(samples))) for c in COLUMNS]
    matrix=[[0.0]*len(COLUMNS) for _ in COLUMNS];target=[0.0]*len(COLUMNS)
    for x,y in samples:
        v=[x[c]/s for c,s in zip(COLUMNS,scales)]
        for i,vi in enumerate(v):
            target[i]+=vi*y
            for j,vj in enumerate(v):matrix[i][j]+=vi*vj
    for i in range(len(COLUMNS)):matrix[i][i]+=RIDGE
    return {'version':VERSION,'columns':COLUMNS,'scales':scales,'coefficients':solve(matrix,target),
            'intercept':0.0,'ridge':RIDGE,'prior_games':PRIOR_GAMES,'training_games':len(samples),
            'status':'RESEARCH CANDIDATE — no automatic promotion'}


def predict(model,values):
    contributions=[]
    for c,s,b in zip(model['columns'],model['scales'],model['coefficients']):
        if values.get(c) is None or not math.isfinite(values[c]):return None
        contributions.append({'feature':c,'label':LABELS[c],'input':values[c],'points':b*values[c]/s})
    return {'margin':sum(row['points'] for row in contributions),'contributions':contributions}
