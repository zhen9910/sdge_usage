import importlib
import json
import os
import tempfile
import unittest
from cryptography.fernet import Fernet


def _make_app():
    """Return a configured Flask test client with a fresh temp DB."""
    key = Fernet.generate_key().decode()
    os.environ['FERNET_KEY'] = key
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    os.environ['DB_PATH'] = tmp.name
    import db
    importlib.reload(db)
    db._fernet = None
    db.init_db()

    import app as flask_app
    importlib.reload(flask_app)
    flask_app.app.config['TESTING'] = True
    flask_app.app.config['SECRET_KEY'] = 'test-secret'
    return flask_app.app.test_client(), db


class TestApiSession(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def test_post_api_session_stores_cookies(self):
        payload = {'uuid': 'test-uuid', 'cookies': [{'name': 'auth', 'value': 'x'}]}
        r = self.client.post('/api/session',
                             data=json.dumps(payload),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(self.db.load_session_cookies('test-uuid'))

    def test_post_api_session_missing_uuid_returns_400(self):
        r = self.client.post('/api/session',
                             data=json.dumps({'cookies': []}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_post_api_session_missing_cookies_returns_400(self):
        r = self.client.post('/api/session',
                             data=json.dumps({'uuid': 'u'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_get_session_status_connected(self):
        self.db.store_session('my-uuid', [{'name': 'a'}])
        r = self.client.get('/api/session/status?uuid=my-uuid')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(json.loads(r.data)['connected'])

    def test_get_session_status_not_connected(self):
        r = self.client.get('/api/session/status?uuid=unknown')
        self.assertFalse(json.loads(r.data)['connected'])

    def test_get_session_status_expired(self):
        self.db.store_session('exp-uuid', [{'name': 'a'}])
        self.db.mark_session_expired('exp-uuid')
        r = self.client.get('/api/session/status?uuid=exp-uuid')
        self.assertFalse(json.loads(r.data)['connected'])


class TestIndexRoute(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def test_index_without_uuid_sets_uuid_cookie(self):
        r = self.client.get('/')
        self.assertIn('uuid', r.headers.get('Set-Cookie', ''))

    def test_index_no_session_shows_landing(self):
        self.client.set_cookie('uuid', 'brand-new-uuid')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Install', r.data)

    def test_index_session_but_no_data_redirects_to_fetch(self):
        self.db.store_session('has-session', [{'name': 'a'}])
        self.client.set_cookie('uuid', 'has-session')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/fetch', r.headers['Location'])

    def test_index_with_data_shows_dashboard(self):
        data = {
            'meter_number': '123',
            'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45',
            'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0,
            'on_peak_kwh': 10.0,
            'total_kwh': -20.0,
            'fetched_at': '2026-04-12T06:00:00',
        }
        self.db.store_session('full-uuid', [{'name': 'a'}])
        self.db.save_data('full-uuid', data)
        self.client.set_cookie('uuid', 'full-uuid')
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Super Off-Peak', r.data)


class TestDisconnect(unittest.TestCase):
    def setUp(self):
        self.client, self.db = _make_app()

    def test_disconnect_clears_session(self):
        self.db.store_session('del-uuid', [{'name': 'a'}])
        self.client.set_cookie('uuid', 'del-uuid')
        self.client.get('/disconnect-sdge')
        self.assertIsNone(self.db.load_session_cookies('del-uuid'))


if __name__ == '__main__':
    unittest.main()
