"""Selectable weekday night windows; combined choices use OR, not AND."""
from datetime import date
NIGHT_OPTIONS=(('thu','Thursday Night'),('sun','Sunday Night'),('mon','Monday Night'),('sat','Saturday Night'),('fri','Friday Night'),('tue','Tuesday Night'),('wed','Wednesday Night'))
WEEKDAYS=('mon','tue','wed','thu','fri','sat','sun')

def normalize_nights(form):
    raw=form.getlist('primetime_nights') if hasattr(form,'getlist') else [form.get('primetime_nights','')]
    chosen={key.strip() for value in raw for key in value.split(',') if key.strip()}
    if chosen-set(dict(NIGHT_OPTIONS)):raise ValueError('Unknown primetime night')
    result=dict(form)
    result['primetime_nights']=','.join(key for key,_ in NIGHT_OPTIONS if key in chosen)
    if chosen:result['primetime']='yes'
    return result

def matches_nights(game,nights):
    if set(nights)-set(WEEKDAYS):raise ValueError('Unknown primetime night')
    try:
        day=date.fromisoformat(game['gameday']).weekday()
        hour,minute=map(int,game['gametime'].split(':'))
    except (ValueError,TypeError,KeyError,AttributeError):return False
    return 19<=hour<=23 and 0<=minute<60 and WEEKDAYS[day] in nights
