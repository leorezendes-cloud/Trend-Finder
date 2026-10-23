"""Bounded, public card-summary cache. No disk writes, forecasts or member HTML."""
import json
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from time import time

WINDOWS = ('1', '3', '5', '10', 'all')
MAX_BYTES = 1024 * 1024
MAX_ENTRY_BYTES = 256 * 1024


class WindowCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def get(self, key, signature, now=None):
        now = time() if now is None else now
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            saved_signature, expires, payload = entry
            if saved_signature != signature or now >= expires:
                self.bytes -= len(payload)
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
        return json.loads(payload)

    def put(self, key, signature, context, now=None):
        if key[0] not in WINDOWS or not isinstance(key[1], bool):
            return False
        now = time() if now is None else now
        # Keep displayed ranges and ranks, not every exploratory match/dataset.
        compact = dict(context, games=[{k: v for k, v in game.items() if k != 'matches'}
                                      for game in context['games']])
        try:
            payload = json.dumps(compact, separators=(',', ':'), allow_nan=False).encode()
        except (TypeError, ValueError):
            return False
        if len(payload) > MAX_ENTRY_BYTES:
            return False
        with self.lock:
            old = self.entries.pop(key, None)
            if old:
                self.bytes -= len(old[2])
            while self.entries and (self.bytes + len(payload) > MAX_BYTES or len(self.entries) >= 10):
                self.bytes -= len(self.entries.popitem(last=False)[1][2])
            # Scheduled kickoffs use minute precision: never cross a minute boundary.
            self.entries[key] = (signature, (int(now)//60+1)*60, payload)
            self.bytes += len(payload)
        return True


def request_key():
    from flask import request
    window = request.args.get('window', 'all')
    return (window if window in WINDOWS else 'all', request.args.get('view') == 'archive')


def source_signature():
    """Stat dependencies and read existing final badges; never fetch a feed here."""
    from flask import current_app, g
    from trend_finder_2 import game_file
    path = Path(game_file).resolve()
    root = path.parent
    paths = (path, root/'public_money_snapshots.csv', root/'manual_spread_overrides.csv',
             root/'research_qb_corrections.csv', root/'data/research_qbs/verified.json',
             root/'sunday_matchups_2026-10-11.csv')
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                      if p.exists() else (str(p), None, None) for p in paths)
    finals = ()
    if current_app.config.get('HOSTED_READ_ONLY_DATA'):
        from fan_views import _score_cache
        rows = g.get('public_confirmed_finals', _score_cache.get('games', []))
        finals = tuple(sorted(tuple(str(row.get(k)) for k in ('away','home','date','away_score','home_score'))
                              for row in rows if row.get('completed') is True and row.get('state') == 'post'))
    return signature, finals


def cache():
    from flask import current_app
    return current_app.extensions.setdefault('historical_window_cache', WindowCache())


def cached_context():
    return cache().get(request_key(), source_signature())


def window_context(builder):
    from flask import g
    context = g.get('historical_window_context')
    if context is not None:
        return context
    key, signature = request_key(), source_signature()
    context = cache().get(key, signature)
    if context is not None:
        return context
    started_minute = int(time()//60)
    context = builder()
    if int(time()//60) == started_minute and source_signature() == signature:
        cache().put(key, signature, context)
    return context
