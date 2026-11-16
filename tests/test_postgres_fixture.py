import builtins
import unittest
from unittest.mock import patch

from foresee.postgres_fixture import PostgresFixture
from foresee.conformance import adapter_suite


class PostgresFixtureGuardTests(unittest.TestCase):
    def test_explicit_dsn_required(self):
        for dsn in (None, '', ' ', 123, {}):
            with self.assertRaisesRegex(ValueError, 'explicit'):
                PostgresFixture(dsn)

    def test_missing_driver_has_actionable_error_without_dsn(self):
        real = builtins.__import__
        def blocked(name, *args, **kwargs):
            if name == 'psycopg':
                raise ImportError('test')
            return real(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=blocked):
            with self.assertRaisesRegex(RuntimeError, r'\[postgres\]') as raised:
                PostgresFixture('password=private-test-value')
            self.assertNotIn('private-test-value', str(raised.exception))

    def test_conformance_cleans_remote_fixture_if_adapter_setup_fails(self):
        closed = []
        class Fixture:
            def connect(self):
                raise RuntimeError('test adapter unavailable')
            def close(self):
                closed.append(True)
        suite = adapter_suite(lambda directory: Fixture(), 'CleanupProbe')
        result = unittest.TestResult()
        # One test is enough to check setup failure cleanup, without running the rest.
        next(iter(suite)).run(result)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(closed, [True])
