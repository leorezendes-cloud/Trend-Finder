"""Read-only links to saved anomaly events; no trend calculations or data writes."""
import csv
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from flask import url_for

ROOT = Path(__file__).resolve().parent

@lru_cache(maxsize=1)
def _index(path, signature):
    events = {}
    try:
        with Path(path).open(newline='', encoding='utf-8-sig') as source:
            for row in csv.DictReader(source):
                if (row.get('category') not in {'game', 'world', 'player', 'team'}
                        or row.get('status') not in {'Confirmed', 'Reported'}
                        or not row.get('event_id') or not row.get('game_id')
                        or not row.get('title', '').strip()
                        or urlparse(row.get('source_url', '')).scheme not in {'http', 'https'}):
                    continue
                try:
                    datetime.fromisoformat(row.get('event_date', ''))
                except ValueError:
                    continue
                events.setdefault(row['game_id'], []).append({
                    'id': row['event_id'], 'title': row['title'],
                    'category': row['category'], 'year': row['event_date'][:4]})
    except (OSError, UnicodeError, csv.Error):
        return {}
    return events

def saved_anomaly_links(game_id, root=None):
    path = Path(root or ROOT)/'anomaly_events.csv'
    try:
        stat = path.stat()
    except OSError:
        return []
    return [{'title': event['title'], 'url': url_for(
        'conspiracy_dungeon_page', panel='anomalies', category=event['category'],
        anomaly_year=event['year'], _anchor='anomaly-'+event['id'])}
        for event in _index(str(path), (stat.st_mtime_ns, stat.st_size)).get(game_id, ())]
