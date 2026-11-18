"""Experimental existing-target PostgreSQL Catalog adapter.

One instance belongs to one caller; concurrent operations use separate instances.
Credentials are connection input only, never a resource path or evidence field.
"""
from copy import deepcopy
from functools import wraps
import re
import uuid

from .catalog import Catalog, Snapshot, commit_identity, stable_digest
from .target_reference import postgres_reference


def _commit_errors(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except self._driver.Error:
            # A transport failure around COMMIT has an unknown outcome. Never
            # expose database diagnostics (which can contain secrets) in reports.
            raise RuntimeError('PostgreSQL commit failed; reconcile the original operation') from None
    return wrapped


class PostgresCatalog:
    def __init__(self, dsn, schema, *, target_name=None):
        self._journal_reference = postgres_reference(target_name, schema) if target_name is not None else None
        if type(dsn) is not str or not dsn.strip():
            raise ValueError('an explicit PostgreSQL DSN is required')
        # A deliberately narrow namespace avoids search_path lists and special schemas.
        if type(schema) is not str or not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', schema) or schema.startswith('pg_') or schema == 'information_schema':
            raise ValueError('an explicit ordinary PostgreSQL schema name is required')
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise RuntimeError('install project-f-bootstrap[postgres] for PostgreSQL support') from None
        self._driver = psycopg
        try:
            self.connection = psycopg.connect(dsn, autocommit=True, connect_timeout=5, row_factory=dict_row)
        except psycopg.Error:
            raise RuntimeError('PostgreSQL connection failed') from None
        try:
            # Put pg_catalog first and exclude public/temp fallback. All application
            # tables are schema-qualified, including when a temporary table exists.
            self.connection.execute('SET search_path = pg_catalog')
            self.connection.execute("SET statement_timeout = '5s'")
            self.connection.execute("SET lock_timeout = '2s'")
            self.connection.execute("SET idle_in_transaction_session_timeout = '10s'")
            from psycopg import sql
            self._sql = sql
            self.schema = schema
            with self.connection.transaction():
                self.connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                self._read_snapshot()
                self._read_target_id()
                self._execute('SELECT commit_id, intent_digest, status, snapshot_digest, resulting_revision, detail FROM {foresee_receipts} LIMIT 0')
        except BaseException:
            self.connection.close()
            raise

    @property
    def journal_reference(self):
        if self._journal_reference is None:
            raise ValueError('PostgreSQL journaling requires a local target name')
        return dict(self._journal_reference)

    def recovery_receipt(self, expected_target_id, commit_id):
        """Read identity and receipt together without changing the target."""
        self._idle()
        if type(commit_id) is not str or not re.fullmatch('[0-9a-f]{64}', commit_id):
            raise ValueError('invalid commit ID')
        with self.connection.transaction():
            self.connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if self._read_target_id() != expected_target_id:
                raise ValueError('target identity mismatch')
            return self._execute('SELECT * FROM {foresee_receipts} WHERE commit_id=%s', (commit_id,)).fetchone()

    def _execute(self, query, params=None):
        tables = ('catalog_rows', 'catalog_meta', 'foresee_target', 'foresee_receipts')
        statement = self._sql.SQL(query).format(**{name: self._sql.Identifier(self.schema, name) for name in tables})
        return self.connection.execute(statement, params)

    def _idle(self):
        if self.connection.closed or self.connection.info.transaction_status != self._driver.pq.TransactionStatus.IDLE:
            raise RuntimeError('operation requires an open idle connection')

    def close(self):
        self.connection.close()

    def _read_target_id(self):
        rows = self._execute('SELECT singleton, target_id FROM {foresee_target}').fetchall()
        if len(rows) != 1 or rows[0]['singleton'] != 1:
            raise ValueError('target identity is missing or invalid')
        value = rows[0]['target_id']
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError('target identity must be a canonical UUID')
        return value

    @property
    def target_id(self):
        self._idle()
        return self._read_target_id()

    def _read_snapshot(self):
        meta = self._execute('SELECT singleton, revision FROM {catalog_meta}').fetchall()
        if len(meta) != 1 or meta[0]['singleton'] != 1 or type(meta[0]['revision']) is not int or not 0 <= meta[0]['revision'] <= 2**63 - 1:
            raise ValueError('catalog revision is missing or invalid')
        revision = meta[0]['revision']
        # Python ordering matches SQLite and pure simulation regardless of DB collation.
        rows = tuple(sorted(self._execute('SELECT id, title, pack_price_cents, units_per_pack, unit_price_cents FROM {catalog_rows}').fetchall(), key=lambda row: row['id']))
        seen = set()
        for row in rows:
            if type(row['id']) is not str or not row['id'] or row['id'] in seen or type(row['title']) is not str:
                raise ValueError('invalid catalog row identity or title')
            seen.add(row['id'])
            for field in ('pack_price_cents', 'units_per_pack', 'unit_price_cents'):
                value = row[field]
                if field == 'unit_price_cents' and value is None:
                    continue
                if type(value) is not int or not (1 if field == 'units_per_pack' else 0) <= value <= 2**63 - 1:
                    raise ValueError('invalid catalog numeric field')
        return Snapshot(revision, rows, stable_digest({'revision': revision, 'rows': rows}))

    def snapshot(self):
        self._idle()
        with self.connection.transaction():
            self.connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return self._read_snapshot()

    def receipt(self, commit_id):
        """Inspect one durable outcome; absence alone does not prove no in-flight write."""
        self._idle()
        if type(commit_id) is not str or not re.fullmatch('[0-9a-f]{64}', commit_id):
            raise ValueError('invalid commit ID')
        return self._execute('SELECT * FROM {foresee_receipts} WHERE commit_id = %s', (commit_id,)).fetchone()

    @_commit_errors
    def commit(self, selection, program_digest, *, operation_id=None, fault_hook=None):
        self._idle()
        selection = deepcopy(selection)
        if not isinstance(selection, dict) or not isinstance(selection.get('base'), dict):
            raise ValueError('selection requires a base snapshot')
        before, plan = selection['base'], selection.get('plan')
        if not isinstance(program_digest, str) or not program_digest:
            raise ValueError('program digest is required')
        if not isinstance(before.get('digest'), str) or not before['digest']:
            raise ValueError('snapshot digest is required')
        Catalog._validate_plan(plan)
        if operation_id is not None and (not isinstance(operation_id, str) or not operation_id or len(operation_id) > 256):
            raise ValueError('operation ID must be a nonempty string of at most 256 characters')
        commit_id, intent_digest = commit_identity(selection, program_digest, operation_id)
        hook = fault_hook or (lambda stage: None)
        hook('before_transaction')
        with self.connection.transaction():
            self.connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE')
            self._execute('LOCK TABLE {catalog_rows} IN SHARE ROW EXCLUSIVE MODE')
            self._execute('SELECT revision FROM {catalog_meta} WHERE singleton=1 FOR UPDATE')
            existing = self._execute('SELECT * FROM {foresee_receipts} WHERE commit_id=%s', (commit_id,)).fetchone()
            if existing:
                if existing['intent_digest'] != intent_digest:
                    raise RuntimeError('operation ID reused with different intent')
                outcome = {'status': existing['status'], 'commit_id': commit_id,
                           'revision': existing['resulting_revision'], 'idempotent_replay': True,
                           'detail': existing['detail']}
            else:
                current = self._read_snapshot()
                revision = current.revision
                if current.digest != before['digest']:
                    status, detail = 'stale', 'target changed after snapshot; no patches applied'
                else:
                    expected = Catalog.apply_to_snapshot(current, plan)
                    if not Catalog.valid_unit_arithmetic(expected):
                        raise ValueError('unit price arithmetic is invalid')
                    if revision == 2**63 - 1:
                        raise ValueError('catalog revision exhausted')
                    for patch in plan['patches']:
                        cursor = self._execute('UPDATE {catalog_rows} SET unit_price_cents=%s WHERE id=%s',
                                               (patch['unit_price_cents'], patch['id']))
                        if cursor.rowcount != 1:
                            raise RuntimeError('commit target disappeared')
                    revision += 1
                    self._execute('UPDATE {catalog_meta} SET revision=%s WHERE singleton=1', (revision,))
                    actual = self._read_snapshot()
                    if actual.rows != expected.rows or actual.revision != revision:
                        raise RuntimeError('commit postcondition failed')
                    status, detail = 'applied', f"applied {len(plan['patches'])} derived-field patches"
                self._execute('INSERT INTO {foresee_receipts} (commit_id, intent_digest, status, snapshot_digest, resulting_revision, detail) VALUES (%s, %s, %s, %s, %s, %s)',
                              (commit_id, intent_digest, status, before['digest'], revision, detail))
                outcome = {'status': status, 'commit_id': commit_id, 'revision': revision,
                           'idempotent_replay': False, 'detail': detail}
            hook('before_commit')
        # The transaction is already durable here. A failed acknowledgment must
        # leave the receipt available for an explicit retry with the same identity.
        hook('after_commit')
        return outcome
