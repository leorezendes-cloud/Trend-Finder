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
            return ('This report is busy. Please try again shortly.', 503,
                    {'Retry-After':'1', 'Cache-Control':'no-store'})
        g.hosted_analytics_gate = True

    @application.teardown_request
    def leave_analytics(error):
        if g.pop('hosted_analytics_gate', False):
            gate.release()
