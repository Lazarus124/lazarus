"""Conexión a SQLite. Una conexión compartida, protegida con un lock."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._con = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA journal_mode = WAL")
        self._con.executescript(SCHEMA.read_text(encoding="utf-8"))
        self._migrate()

    def _migrate(self) -> None:
        """Agrega columnas nuevas a bases creadas con versiones anteriores."""
        cols = {r[1] for r in self._con.execute("PRAGMA table_info(search)")}
        if "remote" not in cols:
            self._con.execute("ALTER TABLE search ADD COLUMN remote INTEGER NOT NULL DEFAULT 0")
        if "level" not in cols:
            self._con.execute("ALTER TABLE search ADD COLUMN level TEXT")
        if "freshness" not in cols:
            self._con.execute("ALTER TABLE search ADD COLUMN freshness TEXT")
        if "modalities" not in cols:
            self._con.execute("ALTER TABLE search ADD COLUMN modalities TEXT")
            self._con.execute("ALTER TABLE search ADD COLUMN part_time INTEGER NOT NULL DEFAULT 0")
            self._con.execute("UPDATE search SET modalities = '[\"remote\"]' WHERE remote = 1")
        if "employment_type" not in {r[1] for r in self._con.execute("PRAGMA table_info(job_analysis)")}:
            self._con.execute("ALTER TABLE job_analysis ADD COLUMN employment_type TEXT")
        job_cols = {r[1] for r in self._con.execute("PRAGMA table_info(job)")}
        if "closed" not in job_cols:
            self._con.execute("ALTER TABLE job ADD COLUMN closed INTEGER NOT NULL DEFAULT 0")
            self._con.execute("ALTER TABLE job ADD COLUMN closed_checked_at TEXT")
        if "file_blob" not in {r[1] for r in self._con.execute("PRAGMA table_info(cv)")}:
            self._con.execute("ALTER TABLE cv ADD COLUMN file_blob BLOB")
        if "posted_on" not in {r[1] for r in self._con.execute("PRAGMA table_info(job_analysis)")}:
            self._con.execute("ALTER TABLE job_analysis ADD COLUMN posted_on TEXT")
        self._con.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._con.execute(sql, params)
            self._con.commit()
            return cur

    def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._con.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._con.close()
