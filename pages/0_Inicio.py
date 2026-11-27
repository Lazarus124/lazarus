import streamlit as st

from lazarus import __version__
from lazarus.claude_client import health
from lazarus.ui import SERVICE_LABELS, claude_panel, page

app = page("Lazarus", "🔎")
st.caption(f"Versión {__version__}")

st.subheader("Antes de empezar")
c1, c2, c3 = st.columns(3)

with c1:
    st.markdown("**Asistente de IA (Claude)**")
    h = st.session_state.get("claude_health") or health(app.cfg["claude"]["binary"])
    st.session_state["claude_health"] = h
    if h["ok"]:
        claude_panel(app, key="home")
    else:
        st.error("Falta instalar Claude.")
        st.link_button("Descargar Claude", "https://claude.com/download")
    if h.get("warning"):
        st.warning(h["warning"])
    if st.button("Volver a comprobar"):
        st.session_state.pop("claude_health", None)
        st.session_state.pop("claude_auth", None)
        st.rerun()

with c2:
    st.markdown("**Dónde buscar**")
    for key, label in (("brightdata", SERVICE_LABELS["brightdata"]), ("firecrawl", SERVICE_LABELS["firecrawl"])):
        if app.cfg["keys"][key]:
            st.success(f"{label}: listo")
        else:
            st.error(f"{label}: falta conectar")
    if not all(app.cfg["keys"].values()):
        st.page_link("pages/6_Configuracion.py", label="Completar en Configuración", icon="⚙️")

with c3:
    st.markdown("**Su CV**")
    cv = app.active_cv()
    if cv:
        st.success(f"Usando: {cv['filename']}")
    else:
        st.warning("Todavía no cargó su CV.")
        st.page_link("pages/1_CV.py", label="Cargar mi CV", icon="📄")

st.subheader("Cómo funciona")
st.markdown(
    "1. **Mi CV**: suba su CV en PDF o Word.\n"
    "2. **Buscar empleo**: escriba qué puesto busca y elija dónde buscar.\n"
    "3. **Vacantes recomendadas**: vea qué tan bien encaja cada oferta con su perfil y por qué.\n"
    "4. **Carta de presentación**: genere una carta, edítela y descárguela.\n"
    "5. **Qué pide el mercado**: vea qué habilidades piden más las empresas.\n\n"
    "Lazarus nunca se postula por usted. Use el enlace de cada oferta para postularse."
)
