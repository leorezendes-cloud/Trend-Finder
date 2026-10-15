"""Immutable live weather-forecast observations; no target-game observed weather."""
import csv,hashlib,io,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from .personnel import ROOT,timestamp
from .shadow import kickoff
from .stats import read_csv,number

VENUE_URL='https://raw.githubusercontent.com/greerreNFL/stadiums/main/data/stadiums.csv'
API='https://api.open-meteo.com/v1/forecast'
FIELDS=('temperature_2m','wind_speed_10m','wind_gusts_10m','precipitation','precipitation_probability')
UNITS={'temperature_2m':'°F','wind_speed_10m':'mp/h','wind_gusts_10m':'mp/h','precipitation':'inch','precipitation_probability':'%'}
ROOFS={'ATL97':('Retractable roof; game setting unconfirmed','https://www.mercedesbenzstadium.com/news/the-roof-at-mercedes-benz-stadium-closes-for-the-first-time'),
       'IND00':('Retractable roof; game setting unconfirmed','https://www.lucasoilstadium.com/tours-stadium-info/background-history/'),
       'LAX01':('Covered venue; field exposure unverified','https://www.sofistadium.com/'),
       'VEG00':('Fixed dome; outside weather is context only','https://www.allegiantstadium.com/news/detail/construction-of-allegiant-stadium-achieves-certificate-of-occupancy-1')}


def extract(payload,game,venue,observed):
    observed=timestamp(observed);ko=kickoff(game)
    if observed>=ko:raise ValueError('Weather observed after kickoff')
    if payload.get('utc_offset_seconds')!=0:raise ValueError('Expected UTC forecast times')
    units=payload.get('hourly_units',{})
    if any(units.get(f)!=UNITS[f] for f in FIELDS):raise ValueError('Unexpected weather units')
    hourly=payload['hourly'];times=[timestamp(t+'Z' if not t.endswith('Z') else t) for t in hourly['time']]
    start=ko.replace(minute=0,second=0,microsecond=0)
    wanted=[start+timedelta(hours=i) for i in range(4)]
    if any(t not in times for t in wanted):raise ValueError('Kickoff window outside supplied forecast horizon')
    window=[]
    for t in wanted:
        index=times.index(t);row={'valid_at_utc':t.isoformat()}
        for f in FIELDS:
            try:v=number(hourly[f][index])
            except (KeyError,IndexError):v=None
            if v is None:raise ValueError('Incomplete forecast window')
            if f!='temperature_2m' and v<0:raise ValueError('Invalid negative weather value')
            if f=='precipitation_probability' and v>100:raise ValueError('Invalid precipitation probability')
            row[f]=v
        window.append(row)
    roof,roof_source=ROOFS.get(game['stadium_id'],('Open-air metadata' if venue.get('roof_type')=='Outdoors' else 'Roof/exposure unknown',VENUE_URL))
    return {'game_id':game['game_id'],'away_team':game['away_team'],'home_team':game['home_team'],
            'kickoff_utc':ko.isoformat(),'stadium_id':game['stadium_id'],'stadium':game['stadium'],
            'requested_latitude':float(venue['lat']),'requested_longitude':float(venue['lon']),
            'grid_latitude':payload.get('latitude'),'grid_longitude':payload.get('longitude'),
            'roof_context':roof,'roof_source':roof_source,'observed_at':observed.isoformat(),
            'model_issued_at':None,'source':'Open-Meteo live forecast','units':UNITS,'hours':window,
            'status':'Separate pregame forecast evidence; not applied to predictions',
            'limitations':['Provider model issuance time not returned; retrieval time controls availability.',
                           'Outside grid forecast, not measured on-field conditions.',
                           'Four hourly samples from kickoff hour through three hours later; not a full-game guarantee.']}


def refresh(root=ROOT,now=None):
    import requests
    now=now or datetime.now(timezone.utc)
    games=[g for g in read_csv(root/'nfl_games.csv') if g['game_type']=='REG' and g.get('gameday') and g.get('gametime') and 0<(kickoff(g)-now).total_seconds()<=7*86400]
    folder=root/'data/scout4/weather'/now.strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True,exist_ok=False)
    response=requests.get(VENUE_URL,timeout=30);response.raise_for_status()
    (folder/'venues.csv').write_bytes(response.content)
    venues={v['stadium_id']:v for v in csv.DictReader(io.StringIO(response.text))}
    records=[];pending=[];meta=[]
    for game in games:
        v=venues.get(game['stadium_id'])
        if not v or number(v.get('lat')) is None or number(v.get('lon')) is None:
            pending.append({'game_id':game['game_id'],'reason':'Missing stadium coordinates'});continue
        params={'latitude':v['lat'],'longitude':v['lon'],'hourly':','.join(FIELDS),'temperature_unit':'fahrenheit',
                'wind_speed_unit':'mph','precipitation_unit':'inch','timezone':'UTC','forecast_days':8}
        try:
            r=requests.get(API,params=params,timeout=30);r.raise_for_status()
            observed=datetime.now(timezone.utc);path=folder/(game['game_id']+'.json')
            path.write_bytes(r.content)
            record=extract(r.json(),game,v,observed.isoformat())
            record['raw_response_sha256']=hashlib.sha256(r.content).hexdigest();record['request_url']=r.url
            records.append(record);meta.append({'game_id':game['game_id'],'request_url':r.url,'observed_at':observed.isoformat(),'sha256':record['raw_response_sha256']})
        except (ValueError,OSError,requests.RequestException) as exc:
            pending.append({'game_id':game['game_id'],'reason':str(exc)})
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'records':records,'pending':pending}
    (folder/'evidence.json').write_text(json.dumps(result,indent=2))
    (folder/'manifest.json').write_text(json.dumps({'venues_url':VENUE_URL,'venues_sha256':hashlib.sha256(response.content).hexdigest(),
        'schedule_sha256':hashlib.sha256((root/'nfl_games.csv').read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'responses':meta},indent=2))
    return result


def view(root=ROOT,now=None):
    now=now or datetime.now(timezone.utc)
    paths=sorted((root/'data/scout4/weather').glob('*/evidence.json'))
    if not paths:return {'records':{},'pending':[]}
    data=json.loads(paths[-1].read_text());records={}
    for r in data['records']:
        r['stale']=(now-timestamp(r['observed_at'])).total_seconds()>86400
        records[r['game_id']]=r
    return {**data,'records':records}

if __name__=='__main__':
    result=refresh();print('Saved',len(result['records']),'weather forecasts;',len(result['pending']),'pending')
