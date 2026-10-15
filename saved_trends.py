"""Readable names for manual searches, including existing saved searches."""
import calendar,json
from urllib.parse import urlsplit,parse_qsl


def manual_trend_title(target):
    values=dict(parse_qsl(urlsplit(target).query,max_num_fields=100))
    labels=[]
    try:
        conditions=json.loads(values.get('combination_conditions','[]'))
        if isinstance(conditions,list):
            for value in conditions:
                if not isinstance(value,str):continue
                if value.startswith('Month: ') and value[7:].isdigit() and 1<=int(value[7:])<=12:value='Month: '+calendar.month_name[int(value[7:])]
                value={'Div Game: 0':'Non-division games','Div Game: 1':'Division games'}.get(value,value)
                labels.append(value)
    except (ValueError,TypeError):pass
    if values.get('location'):labels.append(values['location']+' dogs')
    if values.get('primetime') in ('yes','no'):labels.append('Primetime' if values['primetime']=='yes' else 'Non-primetime')
    mode=values.get('spread_mode')
    if mode=='exact' and values.get('exact_spread'):labels.append('Spread +'+values['exact_spread'])
    elif mode=='min' and values.get('min_spread'):labels.append('Spread +'+values['min_spread']+' or more')
    elif mode=='max' and values.get('max_spread'):labels.append('Spread up to +'+values['max_spread'])
    elif mode=='range':
        low,high=values.get('min_spread'),values.get('max_spread')
        if low or high:labels.append('Spread '+(f'{low}–{high}' if low and high else f'{low}+' if low else f'up to {high}'))
    if values.get('season_mode')=='range' and (values.get('start_season') or values.get('end_season')):
        labels.append(f"Seasons {values.get('start_season','Any')}–{values.get('end_season','Any')}")
    elif values.get('season'):labels.append('Season '+values['season'])
    ignored={'run','action','csrf_token','season','season_mode','start_season','end_season','location','primetime','spread_mode','min_spread','max_spread','exact_spread','combination_conditions','research_view'}
    for key,value in values.items():
        if key in ignored or not value or (key=='research_role' and value=='all'):continue
        label={'research_team':'Team','research_role':'Role','research_location':'Location','spread_size':'Spread'}.get(key,key.replace('_',' ').title().replace('Qb','QB'))
        if key=='month' and value.isdigit() and 1<=int(value)<=12:value=calendar.month_name[int(value)]
        if key=='spread_size':
            value={'pickem':'Pick’em','short':'Up to 3 points','medium':'Over 3 through 7 points','large':'Over 7 through 10 points','double':'Over 10 points'}.get(value,value)
        if key=='div_game':label='Division matchup';value={'0':'No','1':'Yes'}.get(value,value)
        labels.append(f'{label}: {value}')
    title=' | '.join(labels) or ('All NFL games' if values.get('research_view')=='general' else 'All underdog games')
    return title if len(title)<=200 else title[:197].rstrip()+'…'
