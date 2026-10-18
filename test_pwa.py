"""Install metadata, asset availability and release inclusion checks."""
import unittest
from pathlib import Path
from flask import Flask
from pwa import init_app, ASSETS

ROOT = Path(__file__).resolve().parent

class PwaTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, static_folder=str(ROOT / 'static'))
        init_app(app)
        self.client = app.test_client()

    def test_manifest_and_icons(self):
        response = self.client.get('/manifest.webmanifest')
        self.assertEqual(response.mimetype, 'application/manifest+json')
        data = response.json
        self.assertEqual((data['start_url'], data['scope'], data['display']), ('/', '/', 'standalone'))
        for icon in data['icons']:
            asset = self.client.get(icon['src'])
            self.assertEqual(asset.status_code, 200)
            self.assertIn(b'data:image/png;base64,', asset.data)
            asset.close()

    def test_mascot_used_for_app_and_apple_icon(self):
        import base64
        source=(ROOT/'static/Images/Branding_2/trend_findah_crops_and_headers/icon_tf_mascot_large.png')
        # The independent release retains the app copy; the original art can stay local.
        art=(ROOT/'static/pwa/apple-touch-icon.png').read_bytes()
        if source.exists():self.assertEqual(art,source.read_bytes())
        for size in (192,512):
            svg=(ROOT/f'static/pwa/icon-{size}.svg').read_text()
            self.assertIn(base64.b64encode(art).decode(),svg)
        from app import app
        html=app.test_client().get('/install').text
        self.assertIn('pwa/apple-touch-icon.png',html)
        self.assertNotIn('already on the instructions page',html)

    def test_worker_scope_and_version(self):
        response = self.client.get('/service-worker.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
        self.assertEqual(response.headers['Cache-Control'], 'no-cache')
        self.assertNotIn(b'__ASSET_VERSION__', response.data)
        for asset in ASSETS:
            with self.client.get(asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_install_page_and_shared_head(self):
        from app import app
        response = app.test_client().get('/install')
        self.assertEqual(response.status_code, 200)
        for text in ('manifest.webmanifest', 'Add to Home Screen', 'Install app', 'apple-mobile-web-app-capable'):
            self.assertIn(text, response.get_data(as_text=True))
        self.assertIn('How to add to Home Screen',response.text)
        self.assertNotIn('href="https://trendfindah.com/install"',response.text)
        self.assertNotIn('type="button" hidden',response.text)

    def test_release_contains_install_support(self):
        from scripts.prepare_release import release_files
        files = {str(path) for path in release_files()}
        for name in ('pwa.py', 'templates/install.html', 'static/pwa/service-worker.js', 'static/pwa/install.js'):
            self.assertIn(name, files)

if __name__ == '__main__':
    unittest.main()
