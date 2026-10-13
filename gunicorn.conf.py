"""Small SQLite-backed web service; no background collectors."""
import os
from pathlib import Path

chdir = str(Path(__file__).resolve().parent)
bind = '0.0.0.0:' + os.environ.get('PORT', '8000')
workers = 1
worker_class = 'sync'
timeout = 120
# Reset URLs contain credentials; avoid logging request paths.
accesslog = None
errorlog = '-'
capture_output = True
