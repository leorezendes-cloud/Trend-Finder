"""Install metadata and a small offline shell; never caches research or account data."""
import hashlib
from pathlib import Path
from flask import Blueprint, Response, current_app, jsonify, render_template

bp = Blueprint('pwa', __name__)
ASSETS = ('/static/pwa/offline.html', '/static/pwa/icon-192.svg', '/static/pwa/icon-512.svg')


def init_app(app):
    app.register_blueprint(bp)


@bp.get('/manifest.webmanifest')
def manifest():
    response = jsonify(id='/', name='Trendfindah', short_name='Trendfindah',
        description='NFL trends, matchup research, scores and The Plug predictions.',
        start_url='/', scope='/', display='standalone', lang='en',
        background_color='#05080e', theme_color='#05080e',
        icons=[dict(src=f'/static/pwa/icon-{size}.svg', sizes=f'{size}x{size}',
                    type='image/svg+xml', purpose='any') for size in (192, 512)],
        shortcuts=[dict(name='Trend Findah 3000', url='/trend-finder'),
                   dict(name='The Plug', url='/the-plug')])
    response.mimetype = 'application/manifest+json'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@bp.get('/service-worker.js')
def worker():
    root = Path(current_app.static_folder)
    assets = [root / asset.removeprefix('/static/') for asset in ASSETS]
    version = hashlib.sha256(b''.join(path.read_bytes() for path in assets)).hexdigest()[:16]
    source = (root / 'pwa/service-worker.js').read_text().replace('__ASSET_VERSION__', version)
    response = Response(source, mimetype='application/javascript')
    response.headers.update({'Cache-Control':'no-cache', 'Service-Worker-Allowed':'/',
                             'X-Content-Type-Options':'nosniff'})
    return response


@bp.get('/install')
def install():
    return render_template('install.html')
