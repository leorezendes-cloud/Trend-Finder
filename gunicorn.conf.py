"""Small SQLite-backed web service; no background collectors."""
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
