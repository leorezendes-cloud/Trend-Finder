"""One Eastern-time NFL week policy for public pages and member picks."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

EASTERN=ZoneInfo('America/New_York')

def week_window(now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(EASTERN)
    day=now.date()-timedelta(days=(now.weekday()-2)%7)
    start=datetime.combine(day,datetime.min.time(),EASTERN).replace(hour=8)
    if now<start:start-=timedelta(days=7)
    return start,start+timedelta(days=7)

def active_week(rows,now=None):
    start,end=week_window(now)
    groups={}
    for row in rows:
        if row.get('game_type')!='REG':continue
        try:
            date=datetime.fromisoformat(row['gameday']+'T'+(row.get('gametime') or '13:00')).replace(tzinfo=EASTERN)
            key=(int(row['season']),int(row['week']))
        except (KeyError,ValueError):continue
        if start<=date<end:groups[key]=groups.get(key,0)+1
    return max(groups,key=lambda k:(groups[k],k)) if groups else None


def active_slate(rows, now=None):
    """Select the scheduled slate in this Eastern week, never saved forecasts.

    Keep member-pick/frozen-line active_week policy unchanged. Postseason stages
    are distinct from REG even when a provider reuses week numbers.
    """
    start, end = week_window(now)
    groups = {}
    for row in rows:
        if row.get('game_type') not in ('REG', 'WC', 'DIV', 'CON', 'SB'):
            continue
        try:
            kickoff = datetime.fromisoformat(row['gameday']+'T'+(row.get('gametime') or '13:00'))
            kickoff = kickoff.replace(tzinfo=EASTERN) if kickoff.tzinfo is None else kickoff.astimezone(EASTERN)
            key = (int(row['season']), row['game_type'], int(row['week']))
        except (KeyError, ValueError, TypeError):
            continue
        if start <= kickoff < end:
            groups[key] = groups.get(key, 0)+1
    if not groups:
        return None, []
    key = max(groups, key=lambda item: (groups[item], item))
    def identity(row):
        try: return int(row['season']),row['game_type'],int(row['week'])
        except (KeyError,ValueError,TypeError): return None
    selected = [row for row in rows if identity(row) == key]
    return key, selected
