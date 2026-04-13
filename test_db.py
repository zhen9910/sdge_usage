import importlib
import json
import os
import tempfile
import unittest
from cryptography.fernet import Fernet


class TestDb(unittest.TestCase):
    def setUp(self):
        # Generate a fresh key and temp DB for each test
        key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = key
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        os.environ['DB_PATH'] = self._tmp.name

        import db
        importlib.reload(db)       # pick up new env vars
        db._fernet = None          # reset cached Fernet instance
        db.init_db()
        self.db = db

    def tearDown(self):
        self._tmp.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_store_and_load_session(self):
        cookies = [{'name': 'auth', 'value': 'abc', 'domain': '.sdge.com'}]
        self.db.store_session('uuid-1', cookies)
        self.assertEqual(self.db.load_session_cookies('uuid-1'), cookies)

    def test_load_nonexistent_returns_none(self):
        self.assertIsNone(self.db.load_session_cookies('nonexistent'))

    def test_mark_session_expired_nulls_cookies(self):
        self.db.store_session('uuid-1', [{'name': 'a', 'value': 'b'}])
        self.db.mark_session_expired('uuid-1')
        self.assertIsNone(self.db.load_session_cookies('uuid-1'))

    def test_save_and_load_data(self):
        self.db.store_session('uuid-1', [])
        data = {'super_off_peak_kwh': -100.0, 'on_peak_kwh': 50.0, 'fetched_at': '2026-04-12T06:00:00'}
        self.db.save_data('uuid-1', data)
        self.assertEqual(self.db.load_data('uuid-1'), data)

    def test_load_data_returns_none_before_first_fetch(self):
        self.db.store_session('uuid-1', [])
        self.assertIsNone(self.db.load_data('uuid-1'))

    def test_clear_session_removes_row(self):
        self.db.store_session('uuid-1', [])
        self.db.clear_session('uuid-1')
        self.assertIsNone(self.db.load_session_cookies('uuid-1'))
        self.assertIsNone(self.db.load_data('uuid-1'))

    def test_list_active_uuids_excludes_expired(self):
        self.db.store_session('uuid-1', [{'name': 'a'}])
        self.db.store_session('uuid-2', [{'name': 'b'}])
        self.db.mark_session_expired('uuid-1')
        active = self.db.list_active_uuids()
        self.assertNotIn('uuid-1', active)
        self.assertIn('uuid-2', active)

    def test_store_session_overwrites_on_conflict(self):
        self.db.store_session('uuid-1', [{'name': 'old'}])
        self.db.store_session('uuid-1', [{'name': 'new'}])
        result = self.db.load_session_cookies('uuid-1')
        self.assertEqual(result[0]['name'], 'new')


if __name__ == '__main__':
    unittest.main()
