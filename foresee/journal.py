"""Durable intent recording and read-only target reconciliation."""
import json
import sqlite3
import uuid
from pathlib import Path

from .catalog import commit_identity
from .target_reference import validate_reference


class Journal:
    def __init__(self, path: Path, *, existing=False):
        self.path = path.resolve()
        if existing:
            self.connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path)
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, state TEXT NOT NULL, outcome TEXT
                );
                CREATE TABLE IF NOT EXISTS operation_targets (
                    operation_id TEXT PRIMARY KEY, reference TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    target_path TEXT NOT NULL, target_id TEXT NOT NULL,
                    program_digest TEXT NOT NULL, payload TEXT NOT NULL,
                    commit_id TEXT NOT NULL, intent_digest TEXT NOT NULL,
                    state TEXT NOT NULL, outcome TEXT
                );
            """)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA synchronous=FULL")

    def close(self):
        self.connection.close()

    def start(self):
        run_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute("INSERT INTO runs VALUES (?, 'started', NULL)", (run_id,))
        return run_id

    def prepare(self, run_id, catalog, program_digest, payload):
        reference = getattr(catalog, 'journal_reference', None)
        if reference is None:
            target_path = str(catalog.path.resolve())
            if self.path == catalog.path.resolve():
                raise ValueError("journal and target must be separate databases")
        else:
            reference = validate_reference(reference)
            target_path = ''  # Never interpret a remote endpoint as a local path.
        operation_id = str(uuid.uuid4())
        commit_id, intent_digest = commit_identity(payload, program_digest, operation_id)
        with self.connection:
            self.connection.execute("INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', NULL)",
                (operation_id, run_id, target_path, catalog.target_id,
                 program_digest, json.dumps(payload, sort_keys=True), commit_id, intent_digest))
            if reference is not None:
                self.connection.execute("INSERT INTO operation_targets VALUES (?, ?)",
                                        (operation_id, json.dumps(reference, sort_keys=True)))
            self.connection.execute("UPDATE runs SET state='prepared' WHERE run_id=?", (run_id,))
        return operation_id

    def record(self, operation_id, outcome):
        with self.connection:
            self.connection.execute("UPDATE operations SET state=?, outcome=? WHERE operation_id=?",
                                    (outcome["status"], json.dumps(outcome), operation_id))

    def complete(self, run_id, outcome):
        with self.connection:
            self.connection.execute("UPDATE runs SET state='completed', outcome=? WHERE run_id=?",
                                    (json.dumps(outcome), run_id))


def _postgres_receipt(reference, operation, postgres_targets):
    # Local allowlist supplies endpoints. The journal cannot select a host or DSN.
    reference = validate_reference(reference)
    configured = (postgres_targets or {}).get(reference['name'])
    if type(configured) is not dict or set(configured) != {'dsn', 'schema'} or configured['schema'] != reference['schema']:
        raise ValueError('PostgreSQL target is unconfigured or schema differs')
    from .postgres import PostgresCatalog
    adapter = PostgresCatalog(configured['dsn'], configured['schema'])
    try:
        return adapter.recovery_receipt(operation['target_id'], operation['commit_id'])
    finally:
        adapter.close()


def _receipt_result(receipt, operation, payload):
    if receipt is None:
        return {"status": "unresolved", "detail": "no target receipt; no effect inferred or retried"}
    if (receipt["commit_id"] != operation["commit_id"]
            or receipt["intent_digest"] != operation["intent_digest"]
            or receipt["snapshot_digest"] != payload["base"]["digest"]
            or receipt["status"] not in {"applied", "stale"}
            or type(receipt["resulting_revision"]) is not int
            or receipt["resulting_revision"] < 0):
        return {"status": "unresolved", "detail": "target receipt inconsistent with intent"}
    return {"status": receipt["status"], "commit_id": receipt["commit_id"],
            "revision": receipt["resulting_revision"], "detail": receipt["detail"],
            "reconciled": True}


def receipt_outcome(operation, *, postgres_targets=None):
    """Read evidence only. Never initialize a missing target or apply a plan."""
    try:
        operation = dict(operation)
        payload = json.loads(operation["payload"])
        ids = commit_identity(payload, operation["program_digest"], operation["operation_id"])
        if ids != (operation["commit_id"], operation["intent_digest"]):
            return {"status": "unresolved", "detail": "journal intent identity mismatch"}
        if operation.get('target_reference') is not None:
            try:
                reference = json.loads(operation['target_reference'])
                receipt = _postgres_receipt(reference, operation, postgres_targets)
                return _receipt_result(receipt, operation, payload)
            except Exception:
                # Driver errors and local configuration may contain credentials.
                return {"status": "unresolved", "detail": "PostgreSQL recovery evidence unavailable or inconsistent"}
        target = Path(operation["target_path"])
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            identity = connection.execute("SELECT target_id FROM foresee_target WHERE singleton=1").fetchone()
            if identity is None or identity[0] != operation["target_id"]:
                return {"status": "unresolved", "detail": "target identity mismatch"}
            receipt = connection.execute("SELECT * FROM foresee_receipts WHERE commit_id=?", (operation["commit_id"],)).fetchone()
            return _receipt_result(receipt, operation, payload)
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        return {"status": "unresolved", "detail": f"evidence unavailable: {error}"}


def reconcile(path: Path, run_id=None, *, postgres_targets=None):
    journal = Journal(path, existing=True)
    try:
        runs = journal.connection.execute("SELECT * FROM runs WHERE (? IS NULL OR run_id=?) ORDER BY rowid", (run_id, run_id)).fetchall()
        if not runs:
            raise ValueError("no matching journal runs")
        has_references = journal.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operation_targets'").fetchone() is not None
        results = []
        for run in runs:
            operations = journal.connection.execute("SELECT * FROM operations WHERE run_id=? ORDER BY rowid", (run["run_id"],)).fetchall()
            outcomes = []
            for operation in operations:
                operation = dict(operation)
                if has_references:
                    reference = journal.connection.execute("SELECT reference FROM operation_targets WHERE operation_id=?",
                                                           (operation['operation_id'],)).fetchone()
                    if reference is not None:
                        operation['target_reference'] = reference['reference']
                outcome = receipt_outcome(operation, postgres_targets=postgres_targets)
                journal.record(operation["operation_id"], outcome)
                outcomes.append({"operation_id": operation["operation_id"], **outcome})
            resolved = bool(outcomes) and all(o["status"] != "unresolved" for o in outcomes)
            # Reconciled means the recorded operations are known, not that the
            # interrupted program executed its remaining statements.
            state = "reconciled" if resolved else "unresolved"
            if run["state"] == "completed" and (resolved or not operations):
                state = "completed"
            with journal.connection:
                journal.connection.execute("UPDATE runs SET state=? WHERE run_id=?", (state, run["run_id"]))
            results.append({"run_id": run["run_id"], "state": state, "operations": outcomes})
        return {"runs": results, "target_writes": 0}
    finally:
        journal.close()
