"""Piezas compartidas de la UI de Streamlit."""
from __future__ import annotations

import os
import threading
import time

import streamlit as st

from . import config, usage
from .claude_client import ClaudeAuthError, LoginProcess, auth_status, resolve_binary, test_call
from .services import Lazarus, run_id_of


# Nombres para el usuario: sin términos técnicos ni nombres de proveedores donde no hacen falta.
SERVICE_LABELS = {"brightdata": "LinkedIn, Indeed y Glassdoor", "firecrawl": "Portales de empleo"}
SENIORITY = {"intern": "Practicante", "junior": "Junior", "mid": "Semi senior", "senior": "Senior",
             "lead": "Líder", "unknown": "Sin dato", None: "Sin dato"}
MODALITY = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "unknown": "Sin dato", None: "Sin dato"}
RUN_KINDS = {"search": "Búsqueda", "analyze": "Revisión de vacantes", "explain": "Explicaciones",
             "cover_letter": "Carta", "cv_upload": "Carga de CV", "cv_activate": "Cambio de CV",
             "settings": "Configuración", "key_test": "Prueba de conexión",
             "company_research": "Investigación de empresa", "tailor_cv": "CV a medida",
             "job_from_url": "Posición desde un link", "interview_prep": "Guía de entrevista",
             "interview_feedback": "Práctica de entrevista"}
RUN_STATUS = {"ok": "Correcta", "error": "Con error", "running": "En curso"}


@st.cache_resource
def get_app() -> Lazarus:
    from .worker import Worker

    app = Lazarus(config.load())
    app.worker = Worker(app)
    app.worker.resume_pending()  # retoma ofertas sin revisar de sesiones anteriores
    return app


def page(title: str, icon: str = "") -> Lazarus:
    st.set_page_config(page_title=f"Lazarus · {title}", page_icon=icon or None, layout="wide")
    app = get_app()
    sidebar(app)
    st.title(title)
    return app


def sidebar(app: Lazarus) -> None:
    with st.sidebar:
        cv = app.active_cv()
        st.caption("CV activo")
        st.write(cv["filename"] if cv else "Sin CV")
        st.caption("Uso del plan este mes")
        for service, label in SERVICE_LABELS.items():
            s = usage.status(app.db, app.cfg)[service]
            st.progress(min(s["ratio"], 1.0), text=f"{label}: {s['ratio']:.0%}")
            if s["blocked"]:
                st.error(f"{label}: se agotó el plan del mes.")
            elif s["warn"]:
                st.warning(f"{label}: queda poco plan este mes.")
        if app.log.debug:
            st.warning("Diagnóstico detallado activo. Desactívelo en Configuración al terminar.")
        work_status(app)
        auth = st.session_state.get("claude_auth")
        if auth is None and resolve_binary(app.cfg["claude"]["binary"]):
            auth = st.session_state["claude_auth"] = auth_status(app.cfg["claude"]["binary"])
        if st.session_state.get("claude_login") or (auth and not auth["logged_in"]):
            st.divider()
            claude_panel(app, key="sidebar")
        if os.getenv("LAZARUS_LAUNCHER") == "1":
            st.divider()
            if st.button("Cerrar Lazarus", use_container_width=True):
                st.info("Lazarus se cerró. Puede cerrar esta pestaña.")
                threading.Timer(1.0, lambda: os._exit(0)).start()
                st.stop()


@st.fragment(run_every=3)
def work_status(app: Lazarus) -> None:
    """Estado del trabajo en segundo plano. Se actualiza solo cada 3 segundos."""
    worker = getattr(app, "worker", None)
    if not worker:
        return
    for t in worker.active():
        st.divider()
        st.caption("Trabajando en segundo plano")
        label = t.params.get("keyword") or t.params.get("label") or f"búsqueda {t.search_id}"
        if t.total:
            st.progress(t.done / t.total, text=f"{t.stage} ({label}): {t.done} de {t.total}")
        else:
            st.progress(0.0, text=f"{t.stage} ({label})...")
    recent = [t for t in worker.tasks.values() if t.status == "error" and t.finished and time.time() - t.finished < 600]
    for t in recent[-1:]:
        st.error(f"{t.stage}. " + (f"Código de referencia: {t.run_id[:8]}" if t.run_id else ""))
        if t.auth_error:
            st.session_state["claude_auth"] = {"supported": True, "logged_in": False, "email": None}


def task_box(app: Lazarus, key: str, busy_text: str) -> str | None:
    """Muestra el estado de una tarea en segundo plano. Devuelve "busy", "error", "done" o None."""
    t = app.worker.latest_for_key(key)
    if not t:
        return None
    if t.active:
        st.info(f"{busy_text}... Puede seguir usando Lazarus.")
        return "busy"
    if t.status == "error":
        st.error(f"No se pudo completar: {t.error}" + (f" (código de referencia {t.run_id[:8]})" if t.run_id else ""))
        if t.auth_error:
            st.session_state["claude_auth"] = {"supported": True, "logged_in": False, "email": None}
        return "error"
    return "done"


@st.fragment(run_every=3)
def watch_tasks(app: Lazarus, keys: list[str]) -> None:
    """Actualiza la página cuando termina una tarea en segundo plano de esta página."""
    busy = {k for k in keys if (t := app.worker.latest_for_key(k)) and t.active}
    prev = st.session_state.get("_watch_busy", set())
    st.session_state["_watch_busy"] = busy
    if prev - busy:
        st.rerun(scope="app")


def render_research(r: dict) -> None:
    st.markdown(f"**Sobre la empresa** · investigado el {r.get('created_at', '')[:10]}")
    if r.get("ambiguity"):
        st.warning(r["ambiguity"])
    st.write(r.get("summary", ""))
    rows = [("Qué hace", r.get("what_they_do")), ("Tamaño y ubicaciones", r.get("size_and_locations")),
            ("Cultura y opiniones de empleados", r.get("culture_and_reviews"))]
    for label, text in rows:
        if text:
            st.markdown(f"**{label}:** {text}")
    for label, items in (("Productos y tecnología", r.get("products_and_tech")), ("Noticias recientes", r.get("recent_news")),
                         ("Señales de alerta", r.get("red_flags")), ("Preguntas para la entrevista", r.get("questions_to_ask"))):
        if items:
            st.markdown(f"**{label}**\n" + "\n".join(f"- {x}" for x in items))
    if r.get("sources"):
        st.caption("Fuentes: " + " · ".join(f"[{s['title'] or s['url']}]({s['url']})" for s in r["sources"][:8]))


def claude_panel(app: Lazarus, key: str = "main") -> bool:
    """Estado de la sesión de Claude con botón para iniciar sesión. Devuelve True si hay sesión."""
    binary = app.cfg["claude"]["binary"]
    login: LoginProcess | None = st.session_state.get("claude_login")
    if login and not login.done:
        st.info("Se abrió el navegador. Inicie sesión con su cuenta de Claude y apruebe el acceso. "
                "Después vuelva a esta pestaña.")
        for url in login.urls()[:1]:
            st.link_button("Si el navegador no se abrió, haga clic aquí", url)
        c1, c2 = st.columns(2)
        if c1.button("Ya aprobé el acceso", key=f"done_{key}", type="primary"):
            st.rerun()
        if c2.button("Cancelar", key=f"cancel_{key}"):
            login.cancel()
            st.session_state.pop("claude_login", None)
            st.rerun()
        return False
    if login and login.done:
        st.session_state.pop("claude_login", None)
        st.session_state.pop("claude_auth", None)
        if login.returncode != 0:
            st.error("No se completó el inicio de sesión. " + " ".join(login.lines[-3:]))

    status = st.session_state.get("claude_auth") or auth_status(binary)
    st.session_state["claude_auth"] = status
    if status["logged_in"]:
        who = f" como {status['email']}" if status.get("email") else ""
        st.success(f"Claude: sesión iniciada{who}.")
        c1, c2 = st.columns(2)
        if c1.button("Probar conexión", key=f"test_{key}"):
            with st.spinner("Probando..."):
                r = test_call(binary)
            (st.success if r["ok"] else st.error)(r["message"])
            if not r["ok"] and "auth" in r["message"].lower():
                st.session_state["claude_auth"] = {**status, "logged_in": False}
        if c2.button("Iniciar sesión de nuevo", key=f"relogin_{key}"):
            _start_login(binary)
        return True
    st.warning("Claude: no hay una sesión activa.")
    if not status.get("supported", True):
        st.caption(status.get("detail", ""))
    if st.button("Iniciar sesión en Claude", key=f"login_{key}", type="primary"):
        _start_login(binary)
    return False


def _start_login(binary: str) -> None:
    try:
        st.session_state["claude_login"] = LoginProcess(binary)
        st.session_state.pop("claude_auth", None)
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"No pude iniciar el inicio de sesión: {exc}")


def show_error(exc: BaseException, what: str) -> None:
    rid = run_id_of(exc)
    if isinstance(exc, ClaudeAuthError) or isinstance(exc.__cause__, ClaudeAuthError):
        st.error(f"**{what}** — la sesión de Claude venció.")
        st.session_state["claude_auth"] = {"supported": True, "logged_in": False, "email": None}
        claude_panel(get_app(), key="error")
        return
    msg = f"**{what}** — {exc}"
    if rid:
        msg += f"\n\nCódigo de referencia: `{rid[:8]}`. El detalle está en **Actividad y diagnóstico**."
        st.session_state["selected_run"] = rid
    st.error(msg)


def run_note(run_id: str | None) -> None:
    if run_id:
        st.caption(f"Código de referencia: `{run_id[:8]}`")
