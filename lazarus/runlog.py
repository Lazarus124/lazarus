"""Logs de corridas y pasos.

Cada acción del usuario es una corrida (run) con un run_id.
Cada operación dentro de la corrida es un paso (step).
Destinos: JSONL diario, tablas run y run_step, y logs/debug/<run_id>/ en modo debug.
Nunca registra texto del CV, keys ni prompts completos fuera de modo debug.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import DB, now

STDERR_TAIL = 2000


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _short_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:1000]


class Step:
    def __init__(self, name: str, data: dict):
        self.name = name
        self.data = dict(data)

    def set(self, **data) -> None:
        self.data.update(data)


class Run:
    def __init__(self, logger: "RunLogger", kind: str, params: dict):
        self.logger = logger
        self.kind = kind
        self.params = params
        self.id = str(uuid.uuid4())
        self._t0 = time.perf_counter()

    @property
    def short_id(self) -> str:
        return self.id[:8]

    def emit(self, event: str, level: str = "INFO", **fields) -> None:
        self.logger.emit({"level": level, "run_id": self.id, "kind": self.kind, "event": event, **fields})

    @contextmanager
    def step(self, name: str, **data):
        st = Step(name, data)
        started = now()
        t0 = time.perf_counter()
        self.emit("step_start", step=name)
        status, error = "ok", None
        try:
            yield st
        except BaseException as exc:
            status, error = "error", _short_error(exc)
            raise
        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            self.logger.db.execute(
                "INSERT INTO run_step (run_id, name, status, started_at, duration_ms, data_json, error)"
                " VALUES (?,?,?,?,?,?,?)",
                (self.id, name, status, started, ms, json.dumps(st.data, ensure_ascii=False, default=str), error),
            )
            fields = {"step": name, "status": status, "duration_ms": ms, "data": st.data}
            if error:
                fields["error"] = error
            self.emit("step_end", level="ERROR" if error else "INFO", **fields)

    def debug_dump(self, name: str, content: str) -> None:
        """Guarda contenido completo solo en modo debug."""
        if not self.logger.debug:
            return
        folder = self.logger.log_dir / "debug" / self.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(content or "", encoding="utf-8")


class RunLogger:
    def __init__(self, db: DB, log_dir: Path | str, debug: bool = False, retention_days: int = 14):
        self.db = db
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.debug = debug
        self.retention_days = retention_days
        self._lock = threading.Lock()

    def log_file(self, day: str | None = None) -> Path:
        day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"lazarus-{day}.jsonl"

    def emit(self, event: dict) -> None:
        line = json.dumps({"ts": _ts(), **event}, ensure_ascii=False, default=str)
        with self._lock, open(self.log_file(), "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @contextmanager
    def run(self, kind: str, params: dict | None = None):
        r = Run(self, kind, params or {})
        self.db.execute(
            "INSERT INTO run (run_id, kind, status, params_json, started_at) VALUES (?,?,?,?,?)",
            (r.id, kind, "running", json.dumps(r.params, ensure_ascii=False, default=str), now()),
        )
        r.emit("run_start", params=r.params)
        try:
            yield r
        except BaseException as exc:
            self._finish(r, "error", _short_error(exc), traceback.format_exc()[-STDERR_TAIL:])
            try:
                exc.lazarus_run_id = r.id  # la UI muestra este id al usuario
            except AttributeError:
                pass
            raise
        else:
            self._finish(r, "ok")

    def _finish(self, r: Run, status: str, error: str | None = None, tb: str | None = None) -> None:
        ms = int((time.perf_counter() - r._t0) * 1000)
        self.db.execute(
            "UPDATE run SET status = ?, duration_ms = ?, error = ? WHERE run_id = ?",
            (status, ms, error, r.id),
        )
        fields = {"status": status, "duration_ms": ms}
        if error:
            fields.update(error=error, traceback_tail=tb)
        r.emit("run_end", level="ERROR" if error else "INFO", **fields)

    def cleanup(self) -> int:
        """Borra archivos y filas con más de retention_days. Devuelve archivos borrados."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed = 0
        for f in self.log_dir.glob("lazarus-*.jsonl"):
            try:
                day = datetime.strptime(f.stem.split("lazarus-")[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if day < cutoff:
                f.unlink(missing_ok=True)
                removed += 1
        debug_dir = self.log_dir / "debug"
        if debug_dir.exists():
            for d in debug_dir.iterdir():
                if datetime.fromtimestamp(d.stat().st_mtime, timezone.utc) < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
        iso = cutoff.isoformat(timespec="seconds")
        self.db.execute("DELETE FROM run_step WHERE run_id IN (SELECT run_id FROM run WHERE started_at < ?)", (iso,))
        self.db.execute("DELETE FROM run WHERE started_at < ?", (iso,))
        return removed

    def events_for(self, run_id: str) -> list[str]:
        """Líneas JSONL de una corrida (para exportar)."""
        lines = []
        for f in sorted(self.log_dir.glob("lazarus-*.jsonl")):
            with open(f, encoding="utf-8") as fh:
                lines.extend(line for line in fh if run_id in line)
        return lines
