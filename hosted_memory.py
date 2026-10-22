"""Bound simultaneous public analytics allocations on the 512 MiB host."""
from threading import BoundedSemaphore


def install_memory_gate(application):
    if application.config.get('HOSTED_MEMORY_GATE'):
        return
    from flask import g, request
    gate = BoundedSemaphore(1)
    application.config['HOSTED_MEMORY_GATE'] = True

    @application.before_request
    def enter_analytics():
        if (request.endpoint is None or request.endpoint in ('health', 'static')
                or request.blueprint in ('membership', 'newsletter', 'member_picks', 'community', 'huddle_leagues')):
            return
        # Never let queued analytics occupy every Gunicorn thread indefinitely.
        # A busy response bounds the wait even if the active report stalls.
        if not gate.acquire(timeout=1):
            return ('This report is busy. Please try again shortly.', 503,
                    {'Retry-After':'1', 'Cache-Control':'no-store'})
        g.hosted_analytics_gate = True

    @application.teardown_request
    def leave_analytics(error):
        if g.pop('hosted_analytics_gate', False):
            gate.release()
