"""Small SQLite-backed web service with opt-in hosted scheduler threads."""
import os
from pathlib import Path

chdir = str(Path(__file__).resolve().parent)
bind = '0.0.0.0:' + os.environ.get('PORT', '8000')
workers = 1
# Allow CSS/images and health probes to respond during page analysis.
worker_class = 'gthread'
threads = 4
timeout = 120
# Reset URLs contain credentials; avoid logging request paths.
accesslog = None
errorlog = '-'
capture_output = True


def post_worker_init(worker):
    # Prepare the default homepage before this worker accepts public requests.
    from hosted_updates import start_scheduler
    start_scheduler()
    from trend_finder_2 import scan_basic_trends
    scan_basic_trends(season='2026')
    scan_basic_trends(season=(1999, 2025))

# Reset tokens live in URL paths; exclude paths and query strings from access logs.
access_log_format = '%(h)s %(m)s %(s)s %(L)s'
