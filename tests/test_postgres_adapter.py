import unittest
from unittest.mock import patch
import builtins

from foresee.postgres import PostgresCatalog


class PostgresInputTests(unittest.TestCase):
    def test_invalid_configuration_rejected_before_connect(self):
        for dsn in (None, '', ' ', 42):
            with self.assertRaises(ValueError):
                PostgresCatalog(dsn, 'catalog')
        for schema in (None, '', 'public,other', 'pg_temp', 'information_schema', 'a"; DROP SCHEMA public', 'a' * 64):
            with self.assertRaises(ValueError):
                PostgresCatalog('password=secret', schema)

    def test_missing_optional_driver_is_actionable_without_credentials(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'psycopg':
                raise ImportError('missing')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, r'\[postgres\]') as caught:
                PostgresCatalog('password=secret', 'catalog')
        self.assertNotIn('secret', str(caught.exception))
