"""Provisioning/grants contract; disposable CI database requires CREATEROLE."""
from contextlib import closing
import os
from pathlib import Path
import unittest
import uuid

from foresee.catalog import fixture_plans
from foresee.postgres import PostgresCatalog


class PostgresDeploymentTests(unittest.TestCase):
    def test_provisioned_runtime_role_can_commit_but_not_edit_sources_or_receipts(self):
        import psycopg
        from psycopg import sql
        schema = 'foresee_deploy_' + uuid.uuid4().hex
        role = 'foresee_role_' + uuid.uuid4().hex
        script = (Path(__file__).resolve().parents[1] / 'examples/postgres/provision.sql').read_text()
        statement = sql.SQL(script.replace(':"schema"', '{schema}').replace(':"runtime_role"', '{role}')).format(
            schema=sql.Identifier(schema), role=sql.Identifier(role))
        with psycopg.connect(os.environ['FORESEE_TEST_POSTGRES_DSN'], autocommit=True) as owner:
            owner.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
            try:
                owner.execute(statement)
                owner.execute(sql.SQL("INSERT INTO {}.catalog_rows VALUES ('tea', 'Tea', 900, 3, NULL)").format(sql.Identifier(schema)))
                with closing(PostgresCatalog(os.environ['FORESEE_TEST_POSTGRES_DSN'], schema)) as adapter:
                    adapter.connection.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(role)))
                    base = adapter.snapshot()
                    selection = {'base': {'digest': base.digest}, 'plan': fixture_plans(base, 1)[0]}
                    result = adapter.commit(selection, 'deployment-test', operation_id='operation')
                    self.assertEqual(result['status'], 'applied')
                    self.assertEqual(adapter.recovery_receipt(adapter.target_id, result['commit_id'])['status'], 'applied')
                    for query in ('UPDATE {}.catalog_rows SET title=\'tampered\'', 'DELETE FROM {}.foresee_receipts',
                                  'UPDATE {}.foresee_target SET target_id=\'tampered\''):
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            adapter.connection.execute(sql.SQL(query).format(sql.Identifier(schema)))
                with self.assertRaises(psycopg.errors.DuplicateSchema):
                    owner.execute(statement)
                owner.execute('ROLLBACK')
            finally:
                owner.execute('ROLLBACK')
                owner.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
                owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
