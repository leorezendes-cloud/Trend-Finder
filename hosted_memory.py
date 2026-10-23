"""Bound simultaneous public analytics allocations on the 512 MiB host."""
from contextlib import contextmanager
from threading import BoundedSemaphore
from time import monotonic


def home_context(builder):
    """Cache public homepage data only; never cache a rendered member response."""
    from flask import current_app, g
    cached = g.get('hosted_home_context')
    if cached is not None:
        return cached
    context = builder()
    if current_app.config.get('HOSTED_MEMORY_GATE'):
        current_app.extensions['hosted_home_context'] = (monotonic()+60, context)
    return context


@contextmanager
def analytics_network_wait():
    """Release analytics admission for bounded I/O, then reacquire before parsing."""
    from flask import abort, current_app, g, has_request_context
    gate = current_app.extensions.get('hosted_analytics_gate') if has_request_context() else None
    held = gate is not None and g.pop('hosted_analytics_gate', False)
    if held:
        gate.release()
    try:
        yield
    finally:
        if held:
            if not gate.acquire(timeout=1):
                abort(503, description='Analytics are busy. Retry the score refresh shortly.')
            g.hosted_analytics_gate = True


def navigation_loading_response():
    """Small retry page: avoid template processors, research work and shared HTML."""
    from html import escape
    from flask import Response, current_app, url_for
    css = escape(url_for('static',filename='analytics_loading.css'),quote=True)
    script = escape(url_for('static',filename='analytics_loading.js'),quote=True)
    home = escape(url_for('home') if 'home' in current_app.view_functions else '/',quote=True)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Loading your page | Trend Findah</title>
<link rel="stylesheet" href="{css}"><script src="{script}" defer></script></head>
<body><main aria-labelledby="loading-title"><div class="loading-indicator" aria-hidden="true"></div>
<h1 id="loading-title">Loading your page…</h1>
<p id="analytics-loading-status" role="status" aria-live="polite">Another calculation is finishing. This page will retry automatically in a moment.</p>
<nav aria-label="Loading options"><button id="analytics-loading-retry" type="button">Try again</button><a href="{home}">Home</a></nav>
<noscript><p>Refresh this page in a moment to continue.</p></noscript>
</main></body></html>'''
    return Response(html,status=503,mimetype='text/html',headers={
        'Retry-After':'2','Cache-Control':'private, no-store','X-Robots-Tag':'noindex, nofollow',
        'Referrer-Policy':'no-referrer'})


def install_memory_gate(application):
    if application.config.get('HOSTED_MEMORY_GATE'):
        return
    from flask import g, request
    gate = BoundedSemaphore(1)
    application.extensions['hosted_analytics_gate'] = gate
    application.config['HOSTED_MEMORY_GATE'] = True

    @application.before_request
    def enter_analytics():
        if (request.endpoint is None or request.endpoint in ('health', 'static')
                or request.blueprint in ('membership', 'newsletter', 'member_picks', 'community', 'huddle_leagues')):
            return
        if request.endpoint == 'sunday_page' and request.method == 'GET':
            from historical_window_cache import cached_context
            context = cached_context()
            if context is not None:
                g.historical_window_context = context
                return  # Cached public summaries do not perform historical scans.
        is_home = request.endpoint == 'home'
        if is_home and request.method in ('HEAD', 'POST'):
            return  # Probe or legacy-form redirect; neither computes analytics.
        cached = application.extensions.get('hosted_home_context') if is_home and request.method == 'GET' else None
        if cached is not None and monotonic() < cached[0]:
            g.hosted_home_context = cached[1]
            return
        # Never let queued analytics occupy every Gunicorn thread indefinitely.
        # A busy response bounds the wait even if the active report stalls.
        if not gate.acquire(timeout=1):
            if cached is not None:
                g.hosted_home_context = cached[1]
                return  # Reuse the last public snapshot until analytics are free.
            if (request.method == 'GET' and request.accept_mimetypes.best == 'text/html'
                    and not request.path.startswith('/api/') and not request.path.endswith('.json')
                    and 'download' not in request.args):
                return navigation_loading_response()
            return ('This report is busy. Please try again shortly.', 503,
                    {'Retry-After':'1', 'Cache-Control':'no-store'})
        g.hosted_analytics_gate = True

    @application.teardown_request
    def leave_analytics(error):
        if g.pop('hosted_analytics_gate', False):
            gate.release()
