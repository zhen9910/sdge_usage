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


class TestFetchUsageCookiesParam(unittest.TestCase):
    """Verify fetch_current_billing_csv passes cookies= through to Playwright context."""

    def test_fetch_uses_provided_cookies_not_file(self):
        """When cookies= given, load_session_cookies() must NOT be called."""
        import unittest.mock as mock
        import fetch_usage

        fake_cookies = [{'name': 'auth', 'value': 'xyz', 'domain': '.myenergycenter.com'}]

        # Patch at the playwright level so we don't actually launch a browser
        with mock.patch('fetch_usage.sync_playwright') as mock_pw, \
             mock.patch('fetch_usage.load_session_cookies') as mock_load:

            # Set up mock playwright chain
            mock_context = mock.MagicMock()
            mock_page = mock.MagicMock()
            mock_browser = mock.MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page
            mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser

            # Make the page raise so we exit early (we just want to verify cookies were used)
            mock_page.goto.side_effect = Exception('stop early')

            try:
                fetch_usage.fetch_current_billing_csv(cookies=fake_cookies)
            except Exception:
                pass

        mock_load.assert_not_called()
        mock_context.add_cookies.assert_called_once_with(fake_cookies)

    def test_fetch_falls_back_to_file_when_cookies_none(self):
        """When cookies=None, load_session_cookies() must be called."""
        import unittest.mock as mock
        import fetch_usage

        file_cookies = [{'name': 'auth', 'value': 'from_file'}]

        with mock.patch('fetch_usage.sync_playwright') as mock_pw, \
             mock.patch('fetch_usage.load_session_cookies', return_value=file_cookies) as mock_load:

            mock_context = mock.MagicMock()
            mock_page = mock.MagicMock()
            mock_browser = mock.MagicMock()
            mock_browser.new_context.return_value = mock_context
            mock_context.new_page.return_value = mock_page
            mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
            mock_page.goto.side_effect = Exception('stop early')

            try:
                fetch_usage.fetch_current_billing_csv()
            except Exception:
                pass

        mock_load.assert_called_once()
        mock_context.add_cookies.assert_called_once_with(file_cookies)


class TestSaveCurrentBillingDataRouting(unittest.TestCase):
    """Verify save_current_billing_data routes to DB vs file based on uuid param."""

    def setUp(self):
        key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = key
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        os.environ['DB_PATH'] = self._tmp.name
        import db
        importlib.reload(db)
        db._fernet = None
        db.init_db()
        self.db = db

    def tearDown(self):
        self._tmp.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_saves_to_db_when_uuid_given(self):
        """save_current_billing_data(uuid=..., cookies=...) must call db.save_data."""
        import unittest.mock as mock
        import importlib
        import fetch_usage
        importlib.reload(fetch_usage)

        fake_result = {
            'meter_number': '123', 'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45', 'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0, 'on_peak_kwh': 10.0, 'total_kwh': -20.0,
        }
        self.db.store_session('uuid-99', [{'name': 'a'}])

        with mock.patch('fetch_usage.fetch_current_billing_csv', return_value=b'fake,csv'), \
             mock.patch('fetch_usage.iter_rows_csv_stream', return_value=[]), \
             mock.patch('fetch_usage.process', return_value=fake_result.copy()), \
             mock.patch('fetch_usage.db', self.db):

            result = fetch_usage.save_current_billing_data(uuid='uuid-99', cookies=[{'name': 'a'}])

        self.assertIn('fetched_at', result)
        saved = self.db.load_data('uuid-99')
        self.assertIsNotNone(saved)
        self.assertEqual(saved['meter_number'], '123')

    def test_writes_file_when_no_uuid(self):
        """save_current_billing_data() without uuid must write data/current.json."""
        import unittest.mock as mock
        import importlib
        import fetch_usage
        importlib.reload(fetch_usage)

        fake_result = {
            'meter_number': '456', 'reading_start': '3/1/2026 00:00',
            'reading_end': '3/31/2026 23:45', 'super_off_peak_kwh': -50.0,
            'off_peak_kwh': 20.0, 'on_peak_kwh': 10.0, 'total_kwh': -20.0,
        }

        with mock.patch('fetch_usage.fetch_current_billing_csv', return_value=b'fake,csv'), \
             mock.patch('fetch_usage.iter_rows_csv_stream', return_value=[]), \
             mock.patch('fetch_usage.process', return_value=fake_result.copy()), \
             mock.patch('pathlib.Path.write_text') as mock_write:

            fetch_usage.save_current_billing_data()

        mock_write.assert_called_once()


class TestFetchAll(unittest.TestCase):
    def setUp(self):
        key = Fernet.generate_key().decode()
        os.environ['FERNET_KEY'] = key
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        os.environ['DB_PATH'] = self._tmp.name
        import db
        importlib.reload(db)
        db._fernet = None
        db.init_db()
        self.db = db

    def tearDown(self):
        self._tmp.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_fetch_all_calls_save_for_each_active_uuid(self):
        import unittest.mock as mock
        self.db.store_session('uuid-a', [{'name': 'cookie_a'}])
        self.db.store_session('uuid-b', [{'name': 'cookie_b'}])

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data') as mock_save, \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertEqual(mock_save.call_count, 2)
        called_uuids = {call[1]['uuid'] for call in mock_save.call_args_list}
        self.assertIn('uuid-a', called_uuids)
        self.assertIn('uuid-b', called_uuids)

    def test_fetch_all_marks_expired_on_session_error(self):
        import unittest.mock as mock
        self.db.store_session('uuid-bad', [{'name': 'stale'}])

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data', side_effect=Exception('401 Unauthorized')), \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertIsNone(self.db.load_session_cookies('uuid-bad'))

    def test_fetch_all_skips_expired_sessions(self):
        import unittest.mock as mock
        self.db.store_session('uuid-active', [{'name': 'good'}])
        self.db.store_session('uuid-expired', [{'name': 'gone'}])
        self.db.mark_session_expired('uuid-expired')

        import fetch_all
        with mock.patch('fetch_all.save_current_billing_data') as mock_save, \
             mock.patch('fetch_all.db', self.db):
            fetch_all.fetch_all_sessions()

        self.assertEqual(mock_save.call_count, 1)
        self.assertEqual(mock_save.call_args[1]['uuid'], 'uuid-active')


if __name__ == '__main__':
    unittest.main()
