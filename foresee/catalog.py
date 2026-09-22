from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from types import MappingProxyType


def stable_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    revision: int
    rows: tuple[dict[str, Any], ...]
    digest: str

    def __post_init__(self):
        # Catalog row fields are scalar values, so a copied read-only mapping
        # closes the mutable row alias without exposing the source dictionary.
        if any(type(value) not in (str, int, float, bool, type(None)) for row in self.rows for value in row.values()):
            raise ValueError("snapshot row values must be immutable scalars")
        object.__setattr__(self, "rows", tuple(MappingProxyType(dict(row)) for row in self.rows))

    def __deepcopy__(self, memo):
        return self


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalog_meta (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS catalog_rows (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pack_price_cents INTEGER NOT NULL CHECK (pack_price_cents >= 0),
                units_per_pack INTEGER NOT NULL CHECK (units_per_pack > 0),
                unit_price_cents INTEGER
            );
            CREATE TABLE IF NOT EXISTS foresee_receipts (
                commit_id TEXT PRIMARY KEY,
                intent_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                snapshot_digest TEXT NOT NULL,
                resulting_revision INTEGER,
                detail TEXT NOT NULL
            );
            INSERT OR IGNORE INTO catalog_meta(singleton, revision) VALUES (1, 0);
            """
        )
        self.connection.commit()

    def seed(self) -> None:
        count = self.connection.execute("SELECT COUNT(*) FROM catalog_rows").fetchone()[0]
        if count:
            return
        self.connection.executemany(
            "INSERT INTO catalog_rows VALUES (?, ?, ?, ?, ?)",
            [
                ("coffee", "Coffee beans", 1800, 12, None),
                ("filters", "Paper filters", 2400, 24, None),
                ("mugs", "Stoneware mugs", 3600, 6, 600),
            ],
        )
        self.connection.commit()

    def snapshot(self) -> Snapshot:
        revision = self.connection.execute("SELECT revision FROM catalog_meta WHERE singleton = 1").fetchone()[0]
        rows = tuple(dict(row) for row in self.connection.execute("SELECT * FROM catalog_rows ORDER BY id"))
        digest = stable_digest({"revision": revision, "rows": rows})
        return Snapshot(revision, rows, digest)

    @staticmethod
    def apply_to_snapshot(snapshot: Snapshot, plan: dict[str, Any]) -> Snapshot:
        rows = {row["id"]: dict(row) for row in snapshot.rows}
        for patch in plan["patches"]:
            row_id = patch["id"]
            if row_id not in rows:
                raise ValueError(f"unknown catalog row {row_id!r}")
            for field, value in patch.items():
                if field != "id":
                    rows[row_id][field] = value
        ordered = tuple(rows[key] for key in sorted(rows))
        return Snapshot(snapshot.revision, ordered, stable_digest({"revision": snapshot.revision, "rows": ordered}))

    @staticmethod
    def source_fields_unchanged(after: Snapshot, before: Snapshot) -> bool:
        source = ("id", "title", "pack_price_cents", "units_per_pack")
        old = {row["id"]: row for row in before.rows}
        return all(tuple(row[key] for key in source) == tuple(old[row["id"]][key] for key in source) for row in after.rows)

    @staticmethod
    def valid_unit_arithmetic(snapshot: Snapshot) -> bool:
        return all(
            row["unit_price_cents"] is None
            or row["unit_price_cents"] * row["units_per_pack"] == row["pack_price_cents"]
            for row in snapshot.rows
        )

    @staticmethod
    def unresolved_units(snapshot: Snapshot) -> int:
        return sum(row["unit_price_cents"] is None for row in snapshot.rows)

    def mutate_for_stale_test(self) -> None:
        with self.connection:
            self.connection.execute("UPDATE catalog_rows SET title = title || ' (updated)' WHERE id = 'mugs'")
            self.connection.execute("UPDATE catalog_meta SET revision = revision + 1 WHERE singleton = 1")

    def commit(self, selection: dict[str, Any], program_digest: str) -> dict[str, Any]:
        before = selection["base"]
        plan = selection["plan"]
        intent = {
            "program_digest": program_digest,
            "resource": "catalog",
            "snapshot_digest": before["digest"],
            "plan": plan,
        }
        intent_digest = stable_digest(intent)
        commit_id = stable_digest({"intent": intent_digest})[:32]
        existing = self.connection.execute(
            "SELECT * FROM foresee_receipts WHERE commit_id = ?", (commit_id,)
        ).fetchone()
        if existing:
            if existing["intent_digest"] != intent_digest:
                raise RuntimeError("receipt collision with different intent")
            return {
                "status": existing["status"],
                "commit_id": commit_id,
                "revision": existing["resulting_revision"],
                "idempotent_replay": True,
                "detail": existing["detail"],
            }

        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.snapshot()
            if current.digest != before["digest"]:
                detail = "target changed after snapshot; no patches applied"
                self.connection.execute(
                    "INSERT INTO foresee_receipts VALUES (?, ?, 'stale', ?, ?, ?)",
                    (commit_id, intent_digest, before["digest"], current.revision, detail),
                )
                self.connection.commit()
                return {
                    "status": "stale",
                    "commit_id": commit_id,
                    "revision": current.revision,
                    "idempotent_replay": False,
                    "detail": detail,
                }

            allowed = {"unit_price_cents"}
            for patch in plan["patches"]:
                fields = set(patch) - {"id"}
                if not fields <= allowed:
                    raise RuntimeError(f"commit plan contains forbidden fields: {sorted(fields - allowed)}")
                cursor = self.connection.execute(
                    "UPDATE catalog_rows SET unit_price_cents = ? WHERE id = ?",
                    (patch["unit_price_cents"], patch["id"]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"commit target {patch['id']!r} disappeared")
            next_revision = current.revision + 1
            self.connection.execute("UPDATE catalog_meta SET revision = ? WHERE singleton = 1", (next_revision,))
            detail = f"applied {len(plan['patches'])} derived-field patches"
            self.connection.execute(
                "INSERT INTO foresee_receipts VALUES (?, ?, 'applied', ?, ?, ?)",
                (commit_id, intent_digest, before["digest"], next_revision, detail),
            )
            self.connection.commit()
            return {
                "status": "applied",
                "commit_id": commit_id,
                "revision": next_revision,
                "idempotent_replay": False,
                "detail": detail,
            }
        except Exception:
            self.connection.rollback()
            raise


def fixture_plans(snapshot: Snapshot, limit: int) -> list[dict[str, Any]]:
    missing = [row for row in snapshot.rows if row["unit_price_cents"] is None]
    correct = [
        {"id": row["id"], "unit_price_cents": row["pack_price_cents"] // row["units_per_pack"]}
        for row in missing
    ]
    plans = [
        {"id": "complete-derived-repair", "patches": correct},
        {"id": "partial-repair", "patches": correct[:1]},
        {
            "id": "arithmetic-guess",
            "patches": [{"id": row["id"], "unit_price_cents": 1} for row in missing],
        },
        {
            "id": "source-field-edit",
            "patches": ([{"id": missing[0]["id"], "title": "AI rewritten title"}] if missing else []),
        },
    ]
    return plans[:limit]
