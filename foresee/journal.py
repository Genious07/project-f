"""Durable intent recording and read-only target reconciliation."""
import json
import sqlite3
import uuid
from pathlib import Path

from .catalog import commit_identity


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
        if self.path == catalog.path.resolve():
            raise ValueError("journal and target must be separate databases")
        operation_id = str(uuid.uuid4())
        commit_id, intent_digest = commit_identity(payload, program_digest, operation_id)
        with self.connection:
            self.connection.execute("INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared', NULL)",
                (operation_id, run_id, str(catalog.path.resolve()), catalog.target_id,
                 program_digest, json.dumps(payload, sort_keys=True), commit_id, intent_digest))
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


def receipt_outcome(operation):
    """Read evidence only. Never initialize a missing target or apply a plan."""
    try:
        payload = json.loads(operation["payload"])
        ids = commit_identity(payload, operation["program_digest"], operation["operation_id"])
        if ids != (operation["commit_id"], operation["intent_digest"]):
            return {"status": "unresolved", "detail": "journal intent identity mismatch"}
        target = Path(operation["target_path"])
        connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            identity = connection.execute("SELECT target_id FROM foresee_target WHERE singleton=1").fetchone()
            if identity is None or identity[0] != operation["target_id"]:
                return {"status": "unresolved", "detail": "target identity mismatch"}
            receipt = connection.execute("SELECT * FROM foresee_receipts WHERE commit_id=?", (operation["commit_id"],)).fetchone()
            if receipt is None:
                return {"status": "unresolved", "detail": "no target receipt; no effect inferred or retried"}
            if (receipt["intent_digest"] != operation["intent_digest"]
                    or receipt["snapshot_digest"] != payload["base"]["digest"]
                    or receipt["status"] not in {"applied", "stale"}
                    or type(receipt["resulting_revision"]) is not int
                    or receipt["resulting_revision"] < 0):
                return {"status": "unresolved", "detail": "target receipt inconsistent with intent"}
            return {"status": receipt["status"], "commit_id": receipt["commit_id"],
                    "revision": receipt["resulting_revision"], "detail": receipt["detail"],
                    "reconciled": True}
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        return {"status": "unresolved", "detail": f"evidence unavailable: {error}"}


def reconcile(path: Path, run_id=None):
    journal = Journal(path, existing=True)
    try:
        runs = journal.connection.execute("SELECT * FROM runs WHERE (? IS NULL OR run_id=?) ORDER BY rowid", (run_id, run_id)).fetchall()
        if not runs:
            raise ValueError("no matching journal runs")
        results = []
        for run in runs:
            operations = journal.connection.execute("SELECT * FROM operations WHERE run_id=? ORDER BY rowid", (run["run_id"],)).fetchall()
            outcomes = []
            for operation in operations:
                outcome = receipt_outcome(operation)
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
