"""Piezas compartidas de la UI de Streamlit."""
from __future__ import annotations

import os
import threading

import streamlit as st

from . import config, usage
from .claude_client import ClaudeAuthError, LoginProcess, auth_status, resolve_binary, test_call
from .services import Lazarus, run_id_of


@st.cache_resource
def get_app() -> Lazarus:
    return Lazarus(config.load())


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
        st.caption("Consumo del mes")
        for service, label in (("brightdata", "Bright Data (registros)"), ("firecrawl", "Firecrawl (créditos)")):
            s = usage.status(app.db, app.cfg)[service]
            st.progress(min(s["ratio"], 1.0), text=f"{label}: {s['used']:,} / {s['limit']:,}")
            if s["blocked"]:
                st.error(f"{label}: plan agotado. Fuente desactivada.")
            elif s["warn"]:
                st.warning(f"{label}: más del {int(app.cfg['usage']['warn_ratio'] * 100)} % usado.")
        if app.log.debug:
            st.warning("Modo debug activo: los logs guardan contenido completo.")
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
        msg += f"\n\nCorrida `{rid[:8]}`. Vea el detalle en la página **Corridas**."
        st.session_state["selected_run"] = rid
    st.error(msg)


def run_note(run_id: str | None) -> None:
    if run_id:
        st.caption(f"Corrida `{run_id[:8]}`")
