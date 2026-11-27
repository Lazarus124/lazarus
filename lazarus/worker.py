"""Trabajo en segundo plano: búsqueda, revisión de ofertas y explicaciones.

Corre en un hilo propio dentro del proceso de la app. Sigue aunque el usuario cambie
de página o cierre la pestaña del navegador. Al iniciar, retoma las ofertas pendientes.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from .claude_client import ClaudeAuthError
from .services import Lazarus, run_id_of


@dataclass
class Task:
    kind: str                      # "search" | "analyze"
    params: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = "queued"         # queued | running | done | error
    stage: str = "En espera"
    done: int = 0
    total: int = 0
    search_id: int | None = None
    results: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    error: str | None = None
    run_id: str | None = None
    auth_error: bool = False
    created: float = field(default_factory=time.time)
    finished: float | None = None
    fn: object = None              # para tareas "call"
    args: tuple = ()
    result: object = None

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")


class Worker:
    def __init__(self, app: Lazarus):
        self.app = app
        self.q: queue.Queue[Task] = queue.Queue()
        self.tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, name="lazarus-worker", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------- encolar
    def submit_search(self, **params) -> str:
        return self._submit(Task("search", params, stage="En espera para buscar"))

    def submit_analysis(self, search_id: int) -> str | None:
        """Encola la revisión de una búsqueda si no hay otra tarea activa para ella."""
        with self._lock:
            for t in self.tasks.values():
                if t.active and t.search_id == search_id:
                    return t.id
        return self._submit(Task("analyze", {"search_id": search_id}, search_id=search_id, stage="En espera para revisar"))

    def submit_call(self, label: str, key: str, fn, *args) -> str:
        """Encola una tarea simple (investigar empresa, CV a medida, guía de entrevista).
        Si ya hay una activa con la misma clave, devuelve esa."""
        with self._lock:
            for t in self.tasks.values():
                if t.active and t.params.get("key") == key:
                    return t.id
        return self._submit(Task("call", {"label": label, "key": key}, stage=label, fn=fn, args=args))

    def latest_for_key(self, key: str) -> Task | None:
        with self._lock:
            matches = [t for t in self.tasks.values() if t.params.get("key") == key]
        return max(matches, key=lambda t: t.created) if matches else None

    def resume_pending(self) -> int:
        """Encola las búsquedas con ofertas sin revisar (por ejemplo, después de cerrar la app)."""
        rows = self.app.db.query(
            "SELECT DISTINCT sr.search_id FROM search_result sr JOIN job j ON j.id = sr.job_id"
            " WHERE j.analysis_status = 'pending' AND j.duplicate_of IS NULL")
        for r in rows:
            self.submit_analysis(r["search_id"])
        return len(rows)

    def _submit(self, task: Task) -> str:
        with self._lock:
            self.tasks[task.id] = task
        self.q.put(task)
        return task.id

    # ------------------------------------------------------------- consultar
    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def active(self) -> list[Task]:
        with self._lock:
            return [t for t in self.tasks.values() if t.active]

    def for_search(self, search_id: int) -> Task | None:
        with self._lock:
            matches = [t for t in self.tasks.values() if t.search_id == search_id]
        return max(matches, key=lambda t: t.created) if matches else None

    def wait(self, timeout: float = 30) -> None:
        """Espera a que no haya tareas activas (para pruebas)."""
        end = time.time() + timeout
        while self.active() and time.time() < end:
            time.sleep(0.05)

    # ------------------------------------------------------------- ejecutar
    def _loop(self) -> None:
        while True:
            task = self.q.get()
            task.status = "running"
            try:
                if task.kind == "search":
                    self._run_search(task)
                elif task.kind == "call":
                    task.result = task.fn(*task.args)
                else:
                    self._run_analysis(task, task.params["search_id"])
                task.status, task.stage = "done", "Terminado"
            except Exception as exc:  # noqa: BLE001 - se muestra al usuario
                task.status = "error"
                task.error = str(exc)
                task.run_id = run_id_of(exc)
                task.auth_error = isinstance(exc, ClaudeAuthError) or isinstance(exc.__cause__, ClaudeAuthError)
                task.stage = "La sesión de Claude venció" if task.auth_error else "Se detuvo por un error"
            finally:
                task.finished = time.time()

    def _run_search(self, task: Task) -> None:
        task.stage = "Buscando ofertas"
        res = self.app.search(**task.params)
        task.search_id = res["search_id"]
        task.results = res["results"]
        task.summary["reused"] = res["reused"]
        task.run_id = res["run_id"]
        self._run_analysis(task, res["search_id"])

    def _run_analysis(self, task: Task, search_id: int) -> None:
        task.search_id = search_id
        pending = self.app.pending_count(search_id)
        if pending:
            task.stage = "Revisando ofertas"
            task.total, task.done = pending, 0

            def progress(i, n):
                task.done, task.total = i, n

            task.summary["analysis"] = self.app.analyze(search_id, progress=progress)
        if self.app.active_cv():
            task.stage = "Explicando las mejores ofertas"
            task.summary["explain"] = self.app.explain_top(search_id)
