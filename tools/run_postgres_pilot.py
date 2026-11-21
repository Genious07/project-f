"""Measure a synthetic local pilot in a new, exclusively owned Docker database.

No existing endpoint is accepted. Timings include local client overhead and are
observations, not an SLA, throughput benchmark, or production certification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import math
import os
from pathlib import Path
import platform
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foresee.catalog import fixture_plans
from foresee.postgres import PostgresCatalog
from foresee.project import init_project
from check_postgres_faults import OwnedServer, docker

ROOT = Path(__file__).resolve().parents[1]


def distribution(values):
    ordered = sorted(values)
    return {'samples': len(values), 'median_ms': round(statistics.median(values), 3),
            'p95_ms': round(ordered[math.ceil(len(values) * 0.95) - 1], 3),
            'max_ms': round(max(values), 3)}


def cli(root, env, *args):
    started = time.perf_counter()
    result = subprocess.run([sys.executable, '-m', 'foresee', *map(str, args)], cwd=root, env=env,
                            capture_output=True, text=True, timeout=40)
    elapsed = (time.perf_counter() - started) * 1000
    if result.returncode:
        raise AssertionError('pilot CLI failed: ' + args[0])
    return json.loads(result.stdout), elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', default='postgres:18', help='official PostgreSQL 18 tag; may use a cached minor version')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('pilot output already exists')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    result = {'image': args.image, 'scope': 'synthetic-local-docker-pilot', 'status': 'running',
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
              'host': {'system': platform.system(), 'architecture': platform.machine(),
                       'python': platform.python_version(), 'docker': docker('version', '--format', '{{.Server.Version}}')},
              'trials': [], 'concurrency': None, 'cleanup_complete': False,
              'limitations': ['synthetic data', 'single local host', '5 samples per row count',
                              'CLI timings include Python startup', 'no silent-partition, replica-failover, or disk-loss claim']}
    evidence_dir = args.output.parent / (args.output.stem + '-evidence')
    evidence_dir.mkdir(parents=True, exist_ok=False)
    server = OwnedServer(image=args.image)
    try:
        role = 'foresee_pilot_' + uuid.uuid4().hex
        password = secrets.token_hex(24)
        dsn = make_conninfo(server.dsn, user=role, password=password)
        with psycopg.connect(server.dsn, autocommit=True) as owner:
            result['server_version'] = owner.execute('SHOW server_version').fetchone()[0]
            owner.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
            provision = (ROOT / 'examples/postgres/provision.sql').read_text()
            schemas = []
            def target(rows):
                schema = 'foresee_pilot_' + uuid.uuid4().hex
                statement = sql.SQL(provision.replace(':"schema"', '{schema}').replace(':"runtime_role"', '{role}')).format(
                    schema=sql.Identifier(schema), role=sql.Identifier(role))
                owner.execute(statement)
                schemas.append(schema)
                data = [(f'item-{i:04}', f'Synthetic item {i}', (100 + i) * 3, 3, None) for i in range(rows)]
                with owner.cursor() as cursor:
                    cursor.executemany(sql.SQL('INSERT INTO {}.catalog_rows VALUES (%s, %s, %s, %s, %s)').format(sql.Identifier(schema)), data)
                return schema

            def state(schema):
                return {'revision': owner.execute(sql.SQL('SELECT revision FROM {}.catalog_meta').format(sql.Identifier(schema))).fetchone()[0],
                        'receipts': owner.execute(sql.SQL('SELECT count(*) FROM {}.foresee_receipts').format(sql.Identifier(schema))).fetchone()[0],
                        'invalid_rows': owner.execute(sql.SQL('SELECT count(*) FROM {}.catalog_rows WHERE unit_price_cents IS NULL OR unit_price_cents * units_per_pack <> pack_price_cents').format(sql.Identifier(schema))).fetchone()[0]}
            try:
                with tempfile.TemporaryDirectory(prefix='foresee-pilot-') as directory:
                    root = Path(directory)
                    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'PYTHONHOME'}}
                    env.update(PYTHONPATH=str(ROOT), FORESEE_PILOT_DSN=dsn)
                    for rows in (100, 500):
                        for repetition in range(5):
                            schema = target(rows)
                            project = root / f'rows-{rows}-trial-{repetition}'
                            config = init_project(project, target={'adapter': 'postgres', 'name': 'catalog',
                                                                  'schema': schema, 'dsn_env': 'FORESEE_PILOT_DSN'})
                            with closing(PostgresCatalog(dsn, schema)) as adapter:
                                started = time.perf_counter()
                                base = adapter.snapshot()
                                snapshot_ms = (time.perf_counter() - started) * 1000
                                plans = fixture_plans(base, 1)
                                # Verify real restricted-login privileges, not SET ROLE on an owner.
                                for query in ('UPDATE {}.catalog_rows SET title=\'forbidden\'', 'DELETE FROM {}.foresee_receipts',
                                              'UPDATE {}.foresee_target SET target_id=\'forbidden\''):
                                    try:
                                        adapter.connection.execute(sql.SQL(query).format(sql.Identifier(schema)))
                                    except psycopg.errors.InsufficientPrivilege:
                                        pass
                                    else:
                                        raise AssertionError('runtime role exceeded intended permissions')
                            (project / 'plans.json').write_text(json.dumps(plans))
                            outcome, run_ms = cli(root, env, 'run', '--project', config)
                            if outcome['outcome']['status'] != 'applied' or state(schema) != {'revision': 1, 'receipts': 1, 'invalid_rows': 0}:
                                raise AssertionError('repair did not produce exactly the expected state')
                            replay, replay_ms = cli(root, env, 'replay', outcome['report'])
                            if not replay['decision_reproduced']:
                                raise AssertionError('offline replay failed')
                            recovery_times = []
                            for _ in range(2):
                                recovery, elapsed = cli(root, env, 'reconcile', outcome['journal'], '--project', config)
                                recovery_times.append(elapsed)
                                if recovery['target_writes'] != 0 or recovery['runs'][0]['state'] != 'completed':
                                    raise AssertionError('journal reconciliation failed')
                            if state(schema) != {'revision': 1, 'receipts': 1, 'invalid_rows': 0}:
                                raise AssertionError('recovery changed target state')
                            artifact = evidence_dir / f'rows-{rows}-trial-{repetition + 1}'
                            artifact.mkdir()
                            shutil.copyfile(outcome['report'], artifact / 'report.json')
                            shutil.copyfile(outcome['journal'], artifact / 'journal.db')
                            result['trials'].append({'evidence': str(artifact.resolve()), 'rows': rows, 'repetition': repetition + 1, 'snapshot_ms': round(snapshot_ms, 3),
                                'run_cli_ms': round(run_ms, 3), 'replay_cli_ms': round(replay_ms, 3),
                                'reconcile_cli_ms': [round(t, 3) for t in recovery_times],
                                'report_bytes': Path(outcome['report']).stat().st_size, 'state': state(schema), 'permissions_verified': True})
                    schema = target(100)
                    with closing(PostgresCatalog(dsn, schema)) as adapter:
                        base = adapter.snapshot()
                        selection = {'base': {'digest': base.digest}, 'plan': fixture_plans(base, 1)[0]}
                    def contest(operation_ids):
                        ready = threading.Barrier(4)
                        def attempt(index):
                            with closing(PostgresCatalog(dsn, schema)) as adapter:
                                ready.wait(timeout=10)
                                started = time.perf_counter()
                                outcome = adapter.commit(selection, 'pilot-concurrency', operation_id=operation_ids[index])
                                return {'operation': operation_ids[index], 'status': outcome['status'],
                                        'replay': outcome['idempotent_replay'], 'commit_ms': round((time.perf_counter() - started) * 1000, 3)}
                        with ThreadPoolExecutor(max_workers=4) as pool:
                            return list(pool.map(attempt, range(4)))
                    contested = contest([f'worker-{i}' for i in range(4)])
                    applied = [item for item in contested if item['status'] == 'applied']
                    if len(applied) != 1 or sum(item['status'] == 'stale' for item in contested) != 3:
                        raise AssertionError('conflicting snapshots were not serialized')
                    repeated = contest([applied[0]['operation']] * 4)
                    if not all(item['status'] == 'applied' and item['replay'] for item in repeated):
                        raise AssertionError('concurrent idempotent retries failed')
                    final = state(schema)
                    if final != {'revision': 1, 'receipts': 4, 'invalid_rows': 0}:
                        raise AssertionError('concurrency produced unexpected effects or receipts')
                    result['concurrency'] = {'workers': 4, 'rows': 100, 'distinct_operations': contested,
                                             'same_operation_retries': repeated, 'state': final}
            finally:
                owner.execute('ROLLBACK')
                for schema in schemas:
                    owner.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
                owner.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        result['measurements'] = {str(rows): {metric: distribution([trial[metric] for trial in result['trials'] if trial['rows'] == rows])
                                              for metric in ('snapshot_ms', 'run_cli_ms', 'replay_cli_ms')}
                                  for rows in (100, 500)}
        result['status'] = 'passed'
    finally:
        server.close()
        result['cleanup_complete'] = True
    result['evidence_directory'] = str(evidence_dir.resolve())
    encoded = json.dumps(result, indent=2) + '\n'
    if password in encoded or dsn in encoded:
        raise AssertionError('credentials in pilot summary')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        handle.write(encoded)
    print(json.dumps({'status': result['status'], 'report': str(args.output.resolve()), 'measurements': result['measurements']}))


if __name__ == '__main__':
    main()
