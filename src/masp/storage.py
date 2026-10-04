"""SQLite records and ordered events. Agents never receive database access."""

from __future__ import annotations

import builtins
import json
import sqlite3
import threading
import uuid
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from masp.domain import State, check_transition


def now() -> str:
    return datetime.now(UTC).isoformat()


def identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        # Keep WAL open across short transactions; closing the last connection
        # otherwise checkpoints the database on every streamed token.
        self._wal_anchor = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._close_anchor = weakref.finalize(self, self._wal_anchor.close)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, parent TEXT NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY (kind,id));
                CREATE INDEX IF NOT EXISTS records_parent ON records(kind,parent);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id,sequence);
            """)

    def close(self) -> None:
        with self.lock:
            self._close_anchor()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put(self, kind: str, data: dict[str, Any], parent: str = "") -> dict[str, Any]:
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) "
                "DO UPDATE SET data=excluded.data,parent=excluded.parent",
                (kind, data["id"], parent, json.dumps(data, ensure_ascii=False)),
            )
        return data

    def apply_batch(
        self,
        records: list[tuple[str, dict[str, Any], str]],
        deletes: list[tuple[str, str]] | None = None,
    ) -> None:
        """Publish an extension and its components as one inventory transaction."""
        values = [
            (kind, data["id"], parent, json.dumps(data, ensure_ascii=False))
            for kind, data, parent in records
        ]
        with self.lock, self.connect() as db:
            db.executemany(
                "INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) "
                "DO UPDATE SET data=excluded.data,parent=excluded.parent",
                values,
            )
            db.executemany("DELETE FROM records WHERE kind=? AND id=?", deletes or [])

    def get(self, kind: str, key: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM records WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown {kind}: {key}")
        return dict(json.loads(row[0]))

    def delete(self, kind: str, key: str) -> None:
        with self.lock, self.connect() as db:
            cursor = db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))
            if cursor.rowcount == 0:
                raise KeyError(f"Unknown {kind}: {key}")

    def list(self, kind: str, parent: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT data FROM records WHERE kind=? "
                "AND (? IS NULL OR parent=?) ORDER BY rowid DESC",
                (kind, parent, parent),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, kind: str, key: str, **changes: Any) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            row = db.execute(
                "SELECT data FROM records WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
            if row is None:
                raise KeyError(key)
            data = json.loads(row[0])
            data.update(changes)
            db.execute(
                "UPDATE records SET data=? WHERE kind=? AND id=?",
                (json.dumps(data, ensure_ascii=False), kind, key),
            )
            return dict(data)

    def transition(self, kind: str, key: str, state: State) -> dict[str, Any]:
        with self.lock:
            record = self.get(kind, key)
            check_transition(record["state"], state)
            record = self.update(kind, key, state=state.value, updated_at=now())
            run_id = key if kind == "run" else record["run_id"]
            self.event(
                run_id, f"{kind}.state", {"state": state.value}, key if kind == "task" else None
            )
            return record

    def event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "event_id": identifier("evt"),
            "timestamp": now(),
            "run_id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "type": event_type,
            "payload": payload,
        }
        with self.lock, self.connect() as db:
            cursor = db.execute(
                "INSERT INTO events(run_id,data) VALUES (?,?)",
                (run_id, json.dumps(event, ensure_ascii=False)),
            )
            event["sequence"] = cursor.lastrowid
        return event

    def events(self, run_id: str, after: int = 0) -> builtins.list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT sequence,data FROM events WHERE run_id=? AND sequence>? "
                "ORDER BY sequence LIMIT 500",
                (run_id, after),
            ).fetchall()
        return [dict(json.loads(data), sequence=sequence) for sequence, data in rows]
