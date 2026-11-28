"""Piezas compartidas de la UI de Streamlit."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import streamlit as st

from . import config, usage
from .claude_client import ClaudeAuthError, LoginProcess, auth_status, resolve_binary, test_call
from .services import Lazarus, run_id_of


# Nombres para el usuario: sin términos técnicos ni nombres de proveedores donde no hacen falta.
SERVICE_LABELS = {"brightdata": "LinkedIn, Indeed y Glassdoor", "firecrawl": "Portales de empleo"}
SENIORITY = {"intern": "Practicante", "junior": "Junior", "mid": "Semi senior", "senior": "Senior",
             "lead": "Líder", "unknown": "Sin dato", None: "Sin dato"}
# Nivel con años de experiencia, para quien no conoce los términos de la industria.
LEVEL_LABELS = {"intern": "Practicante · sin experiencia", "junior": "Junior · 0 a 2 años",
                "mid": "Semi senior · 2 a 5 años", "senior": "Senior · 5 a 8 años",
                "lead": "Líder · más de 8 años", "unknown": "Sin dato", None: "Sin dato"}
TRACK_LABELS = {"favorito": "⭐ Favorita", "aplicado": "✅ Me postulé", "no_me_gusta": "👎 No me gusta",
                "no_mostrar": "🚫 Oculta"}


def open_folder(path) -> bool:
    """Abre una carpeta en el Explorador de Windows. Devuelve False en otros sistemas."""
    Path(path).mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606 - carpeta local del usuario
        return True
    return False


def tracking_buttons(app: Lazarus, job_id: int, current: str | None, key: str) -> None:
    """Botones para marcar una posición: favorita, me postulé, no me gusta, ocultar."""
    cols = st.columns(4)
    for col, status in zip(cols, ("favorito", "aplicado", "no_me_gusta", "no_mostrar")):
        active = current == status
        if col.button(TRACK_LABELS[status], key=f"tr_{status}_{key}", type="primary" if active else "secondary",
                      use_container_width=True, help="Toque otra vez para quitar la marca" if active else None):
            res = app.set_status(job_id, None if active else status)
            if res.get("files"):
                st.session_state[f"saved_{job_id}"] = res["files"]
            st.rerun()


FRESHNESS = {None: "Cualquier fecha", "day": "Últimas 24 horas", "3days": "Últimos 3 días",
             "week": "Última semana", "month": "Último mes"}


def age_label(posted_on: str | None) -> str:
    """'hoy', 'ayer', 'hace 5 días'… desde una fecha AAAA-MM-DD."""
    if not posted_on:
        return "Sin fecha"
    from datetime import date
    try:
        days = (date.today() - date.fromisoformat(posted_on)).days
    except ValueError:
        return "Sin fecha"
    return "Hoy" if days <= 0 else "Ayer" if days == 1 else f"Hace {days} días" if days < 31 else f"Hace {days // 30} meses"


EMPLOYMENT = {"full_time": "Tiempo completo", "part_time": "Part time", "contract": "Por proyecto",
              "internship": "Pasantía", "unknown": "Sin dato", None: "Sin dato"}
MODALITY = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial", "unknown": "Sin dato", None: "Sin dato"}
RUN_KINDS = {"search": "Búsqueda", "analyze": "Revisión de vacantes", "explain": "Explicaciones",
             "cover_letter": "Carta", "cv_upload": "Carga de CV", "cv_activate": "Cambio de CV",
             "settings": "Configuración", "key_test": "Prueba de conexión",
             "company_research": "Investigación de empresa", "tailor_cv": "CV a medida",
             "job_from_url": "Posición desde un link", "interview_prep": "Guía de entrevista",
             "interview_feedback": "Práctica de entrevista", "verify_open": "Verificar posición",
             "tracking": "Seguimiento", "interview_stage": "Preparación de etapa",
             "learning_plan": "Plan de estudio", "tutor_chat": "Chat con el tutor"}
RUN_STATUS = {"ok": "Correcta", "error": "Con error", "running": "En curso"}


@st.cache_resource
def get_app() -> Lazarus:
    from .worker import Worker

    app = Lazarus(config.load())
    app.worker = Worker(app)
    app.worker.resume_pending()  # retoma ofertas sin revisar de sesiones anteriores
    return app


ASSETS = Path(__file__).parent / "assets"
ICON = str(ASSETS / "icon.png")


def page(title: str, icon: str = "", show_title: bool = True) -> Lazarus:
    st.set_page_config(page_title=f"Lazarus · {title}", page_icon=ICON, layout="wide")
    st.logo(ICON, icon_image=ICON, size="large")
    app = get_app()
    sidebar(app)
    if show_title:
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
        st.error(f"{t.stage}: {(t.error or '')[:300]}" + (f"\n\nCódigo de referencia: {t.run_id[:8]}" if t.run_id else ""))
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
