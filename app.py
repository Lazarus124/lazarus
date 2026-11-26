"""Lazarus: página de inicio y estado del sistema."""
import streamlit as st

from lazarus import __version__
from lazarus.claude_client import health
from lazarus.ui import claude_panel, page

app = page("Lazarus", "🔎")
st.caption(f"Versión {__version__} · Datos en `{app.cfg['paths']['data']}`")

st.subheader("Estado del sistema")
c1, c2, c3 = st.columns(3)

with c1:
    h = st.session_state.get("claude_health") or health(app.cfg["claude"]["binary"])
    st.session_state["claude_health"] = h
    if h["ok"]:
        st.caption(f"Claude Code {h['version']}")
        claude_panel(app, key="home")
    else:
        st.error("Claude Code no está instalado.")
        st.link_button("Descargar Claude Code", "https://claude.com/download")
    if h.get("warning"):
        st.warning(h["warning"])
    if st.button("Volver a comprobar"):
        st.session_state.pop("claude_health", None)
        st.session_state.pop("claude_auth", None)
        st.rerun()

with c2:
    for name, key in (("Bright Data", "brightdata"), ("Firecrawl", "firecrawl")):
        if app.cfg["keys"][key]:
            st.success(f"Key de {name}: presente")
        else:
            st.error(f"Key de {name}: falta")
    if not all(app.cfg["keys"].values()):
        st.page_link("pages/6_Configuracion.py", label="Cargar las claves en Configuración", icon="⚙️")

with c3:
    cv = app.active_cv()
    if cv:
        st.success(f"CV activo: {cv['filename']}")
    else:
        st.warning("No hay CV. Vaya a la página CV.")

st.subheader("Recorrido")
st.markdown(
    "1. **CV**: suba su CV en PDF o DOCX.\n"
    "2. **Buscar**: elija rol, ubicación y fuentes.\n"
    "3. **Vacantes**: revise el ranking, el score y las razones.\n"
    "4. **Carta**: genere, edite y descargue la carta.\n"
    "5. **Mercado**: vea qué piden las empresas.\n\n"
    "Lazarus nunca aplica por usted. Use el enlace original de cada vacante para aplicar."
)
