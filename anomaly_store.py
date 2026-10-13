"""Append user-entered sourced events without modifying the NFL results database."""
import csv,fcntl,uuid
from datetime import date
from urllib.parse import urlparse
from anomaly_analysis import FIELDS,CATEGORIES

def add_event(root,form):
    event={field:str(form.get(field,'')).strip() for field in FIELDS}
    event['event_id']=uuid.uuid4().hex
    if event['category'] not in CATEGORIES:raise ValueError('Choose an event category.')
    if event['status'] not in {'Confirmed','Reported'}:raise ValueError('Choose Confirmed or Reported.')
    try:date.fromisoformat(event['event_date'])
    except ValueError:raise ValueError('Enter an event date.')
    if not event['title'] or not event['description']:raise ValueError('Title and description are required.')
    if any(len(event[key])>limit for key,limit in [('title',200),('description',4000),('team',20),('player',100),('game_id',80),('source_url',2000)]):raise ValueError('One of the event fields is too long.')
    url=urlparse(event['source_url'])
    if url.scheme not in {'http','https'} or not url.netloc:raise ValueError('Enter a valid public source link.')
    logs=root/'logs';logs.mkdir(exist_ok=True)
    with (logs/'anomaly_events.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        target=root/'anomaly_events.csv';rows=[]
        if target.exists():
            with target.open(newline='') as f:
                reader=csv.DictReader(f)
                if reader.fieldnames!=FIELDS:raise ValueError('Event database has an unexpected header.')
                rows=list(reader)
        temp=target.with_suffix('.tmp')
        with temp.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows);w.writerow(event)
        temp.replace(target)
    return event
