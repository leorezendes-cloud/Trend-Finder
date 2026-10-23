"""Concurrency/response checks with isolated Flask apps only."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from flask import Flask
from hosted_memory import install_memory_gate


class HostedMemoryTests(unittest.TestCase):
    def test_health_remains_available_and_reports_do_not_overlap(self):
        app = Flask(__name__)
        entered, release = threading.Event(), threading.Event()
        lock = threading.Lock()
        active = maximum = 0

        @app.get('/report')
        def report():
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            release.wait(3)
            with lock:
                active -= 1
            return 'same report'

        @app.get('/healthz', endpoint='health')
        def health():
            return 'healthy'

        install_memory_gate(app)
        install_memory_gate(app)  # duplicate installation must not deadlock
        def get(path):
            with app.test_client() as client:
                return client.get(path).data
        with ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(get, '/report')
            try:
                self.assertTrue(entered.wait(2))
                second = pool.submit(get, '/report')
                self.assertEqual(pool.submit(get, '/healthz').result(timeout=2), b'healthy')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), b'same report')
            self.assertEqual(second.result(timeout=2), b'same report')
        self.assertEqual(maximum, 1)

    def test_exception_releases_gate_and_exempt_endpoints_work(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        @app.get('/broken')
        def broken():
            raise ValueError('fixture')
        @app.get('/fine')
        def fine():
            return 'fine'
        install_memory_gate(app)
        with app.test_client() as client:
            with self.assertRaises(ValueError):
                client.get('/broken')
            self.assertEqual(client.get('/fine').data, b'fine')
            self.assertEqual(client.get('/missing').status_code, 404)

    def test_saturated_four_thread_pool_can_answer_health_probe(self):
        import time
        app = Flask(__name__)
        entered, release = threading.Event(), threading.Event()
        @app.get('/slow')
        def slow():
            entered.set()
            release.wait(5)
            return 'done'
        @app.get('/healthz', endpoint='health')
        def health(): return 'healthy'
        install_memory_gate(app)
        def get(path):
            with app.test_client() as client:
                response = client.get(path)
                return response.status_code, response.headers.get('Retry-After')
        with ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(get, '/slow')
            try:
                self.assertTrue(entered.wait(2))
                queued = [pool.submit(get, '/slow') for _ in range(3)]
                started = time.monotonic()
                self.assertEqual(pool.submit(get, '/healthz').result(timeout=3)[0], 200)
                self.assertLess(time.monotonic()-started, 3)
                self.assertEqual([f.result(timeout=2) for f in queued], [(503,'1')]*3)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2)[0], 200)

    def test_hosted_mutation_protection_precedes_busy_admission(self):
        from test_hosting import HostingTests
        app = HostingTests().make_app()
        entered, release = threading.Event(), threading.Event()
        @app.get('/slow')
        def slow():
            entered.set(); release.wait(3)
            return 'done'
        def get():
            with app.test_client() as client: return client.get('/slow').status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(get)
            try:
                self.assertTrue(entered.wait(2))
                def forbidden():
                    with app.test_client() as client: return client.post('/refresh').status_code
                self.assertEqual(pool.submit(forbidden).result(timeout=.8), 403)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), 200)


class HomeCacheTests(unittest.TestCase):
    def make_app(self):
        from flask import request, session, redirect
        from hosted_memory import home_context
        app = Flask(__name__)
        app.secret_key = 'isolated-cache-tests'
        calls = []
        entered, release = threading.Event(), threading.Event()

        def build():
            calls.append(True)
            return {'title': 'Public trends'}

        @app.route('/', methods=['GET', 'HEAD', 'POST'], endpoint='home')
        def home():
            if request.method == 'HEAD':
                return '', 200
            if request.method == 'POST':
                return redirect('/research', 307)
            context = home_context(build)
            return context['title'] + ':' + session.get('viewer', 'guest')

        @app.get('/plug', endpoint='plug_page')
        def plug():
            entered.set()
            release.wait(5)
            return 'Plug'

        install_memory_gate(app)
        return app, calls, entered, release

    def test_fresh_and_stale_home_data_remain_available_during_plug(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                app, calls, entered, release = self.make_app()
                client = app.test_client()
                self.assertEqual(client.get('/').status_code, 200)
                if stale:
                    app.extensions['hosted_home_context'] = (0, app.extensions['hosted_home_context'][1])
                def plug():
                    with app.test_client() as other:
                        return other.get('/plug').status_code
                with ThreadPoolExecutor(max_workers=2) as pool:
                    running = pool.submit(plug)
                    try:
                        self.assertTrue(entered.wait(2))
                        response = client.get('/')
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(b'Public trends', response.data)
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(client.head('/').status_code, 200)
                        self.assertEqual(client.post('/').status_code, 307)
                    finally:
                        release.set()
                    self.assertEqual(running.result(timeout=2), 200)

    def test_cache_does_not_share_member_rendering_and_refreshes_when_free(self):
        app, calls, _, _ = self.make_app()
        first, second = app.test_client(), app.test_client()
        with first.session_transaction() as session:
            session['viewer'] = 'first-member'
        with second.session_transaction() as session:
            session['viewer'] = 'second-member'
        self.assertEqual(first.get('/').data, b'Public trends:first-member')
        self.assertEqual(second.get('/').data, b'Public trends:second-member')
        self.assertEqual(app.test_client().get('/').data, b'Public trends:guest')
        self.assertEqual(len(calls), 1)
        app.extensions['hosted_home_context'] = (0, app.extensions['hosted_home_context'][1])
        self.assertEqual(second.get('/').status_code, 200)
        self.assertEqual(len(calls), 2)

    def test_cold_home_does_not_bypass_memory_guard(self):
        app, calls, entered, release = self.make_app()
        def plug():
            with app.test_client() as client:
                return client.get('/plug').status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(plug)
            try:
                self.assertTrue(entered.wait(2))
                response = app.test_client().get('/')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.headers['Retry-After'], '1')
                self.assertEqual(calls, [])
            finally:
                release.set()
            self.assertEqual(running.result(timeout=2), 200)
        self.assertEqual(app.test_client().get('/').status_code, 200)
        self.assertEqual(len(calls), 1)
