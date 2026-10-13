"""Hosting entry point. Local app.py behavior remains unchanged."""
import os
from pathlib import Path

from flask import abort, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

# Legacy public analysis reads several files relative to the project directory.
os.chdir(Path(__file__).resolve().parent)
from app import app


def configure_hosted_app(application):
    if application.config.get('HOSTING_CONFIGURED'):
        return
    application.config['HOSTING_CONFIGURED'] = True
    application.config['HOSTED_READ_ONLY_DATA'] = True
    hops = int(os.environ.get('TREND_FINDAH_PROXY_HOPS', '0'))
    if not 0 <= hops <= 3:
        raise RuntimeError('TREND_FINDAH_PROXY_HOPS must be between 0 and 3')
    if hops:
        application.wsgi_app = ProxyFix(application.wsgi_app, x_for=hops, x_proto=hops,
                                       x_host=0, x_port=0, x_prefix=0)

    @application.before_request
    def protect_research_data():
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            # Public analysis is read-only even though it submits a POST form.
            if request.endpoint not in ('home', 'trend_finder') and request.blueprint != 'membership':
                abort(403, description='Data refresh and research editing are available only in the local research app.')

    @application.get('/healthz')
    def health():
        from membership import db
        db().execute('SELECT 1').fetchone()
        return jsonify(status='ok')


configure_hosted_app(app)
