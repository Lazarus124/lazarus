import streamlit as st

from lazarus import __version__
from lazarus.claude_client import health
from lazarus.ui import ICON, SERVICE_LABELS, claude_panel, page

app = page("Inicio", show_title=False)

# Estilo de marca: tarjeta principal con tinte naranja y pasos con borde superior naranja.
st.markdown("""
<style>
.st-key-hero { background: rgba(194, 88, 43, 0.10); border: 1px solid rgba(194, 88, 43, 0.45);
               border-radius: 0.6rem; padding: 1.4rem 1.6rem; }
.st-key-hero p.kicker, p.kicker { color: #C2582B; font-size: 0.78rem; letter-spacing: 0.04em; margin: 0; }
[class*="st-key-step_"] { border-top: 3px solid #C2582B !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- estado
h = st.session_state.get("claude_health") or health(app.cfg["claude"]["binary"])
st.session_state["claude_health"] = h
auth = st.session_state.get("claude_auth") or {}
claude_ok = h["ok"] and auth.get("logged_in", True)
keys_ok = all(app.cfg["keys"].values())
cv = app.active_cv()
has_search = bool(app.searches(limit=1))

STEPS = [
    ("cv", "Tu CV", "Súbelo en PDF o Word", "pages/1_CV.py", bool(cv)),
    ("buscar", "Buscar", "Puesto, país y fuentes", "pages/2_Buscar.py", has_search),
    ("vacantes", "Vacantes", "Afinidad y razones", "pages/3_Vacantes.py", False),
    ("carta", "Carta", "Edítala y descárgala", "pages/4_Carta.py", False),
    ("entrevista", "Entrevista", "Prepárate por etapas", "pages/8_Entrevista.py", False),
]

if not h["ok"]:
    title, nxt, target, cta = "Falta instalar el asistente de IA", "Instala Claude para empezar.", None, None
elif not claude_ok:
    title, nxt, target, cta = "Conecta el asistente de IA", "Inicia sesión en Claude con el botón de abajo.", None, None
elif not keys_ok:
    title, nxt, target, cta = "Conecta las fuentes de empleo", "Pega tus claves en Configuración.", "pages/6_Configuracion.py", "Ir a Configuración"
elif not cv:
    title, nxt, target, cta = "Sube tu CV para empezar", "Lazarus usa tu CV para encontrar posiciones a tu medida.", "pages/1_CV.py", "Subir mi CV"
elif not has_search:
    title, nxt, target, cta = "Todo está listo para buscar", "Tu siguiente paso: haz tu primera búsqueda.", "pages/2_Buscar.py", "Buscar empleo"
else:
    title, nxt, target, cta = "Todo está listo para buscar", "Tu siguiente paso: revisa tus vacantes recomendadas.", "pages/3_Vacantes.py", "Ver vacantes"
next_key = next((k for k, *_, done in STEPS if not done), "vacantes")

# ------------------------------------------------------------------ hero
with st.container(key="hero"):
    c1, c2, c3 = st.columns([1, 6, 3], vertical_alignment="center")
    c1.image(ICON, width=72)
    with c2:
        st.markdown(f'<p class="kicker">LAZARUS · VERSIÓN {__version__}</p>', unsafe_allow_html=True)
        st.markdown(f"## {title}")
        st.write(nxt)
    if target and c3.button(cta, type="primary", icon=":material/work:", use_container_width=True):
        st.switch_page(target)

# ----------------------------------------------------------------- tarjetas
c1, c2, c3 = st.columns(3)
with c1.container(border=True, height="stretch"):
    st.markdown("**:material/smart_toy: Asistente de IA**")
    if not h["ok"]:
        st.markdown(":red[:material/cancel: Falta instalar Claude]")
        st.link_button("Descargar Claude", "https://claude.com/download")
    elif claude_ok:
        st.markdown(":green[:material/check_circle: Conectado]")
        with st.popover("Opciones", icon=":material/more_horiz:"):
            claude_panel(app, key="home")
            if st.button("Volver a comprobar"):
                st.session_state.pop("claude_health", None)
                st.session_state.pop("claude_auth", None)
                st.rerun()
    else:
        claude_panel(app, key="home")
    if h.get("warning"):
        st.caption(h["warning"])

with c2.container(border=True, height="stretch"):
    st.markdown("**:material/travel_explore: Fuentes de empleo**")
    for key in ("brightdata", "firecrawl"):
        ok = bool(app.cfg["keys"][key])
        st.markdown((":green[:material/check_circle:]" if ok else ":red[:material/cancel:]") + f" {SERVICE_LABELS[key]}")
    if not keys_ok:
        st.page_link("pages/6_Configuracion.py", label="Conectar en Configuración", icon=":material/arrow_forward:")

with c3.container(border=True, height="stretch"):
    st.markdown("**:material/description: Tu CV**")
    if cv:
        st.markdown(f":green[:material/check_circle:] {cv['filename']}")
        st.page_link("pages/1_CV.py", label="Cambiar CV", icon=":material/swap_horiz:")
    else:
        st.markdown(":orange[:material/upload_file:] Todavía no subiste tu CV")
        st.page_link("pages/1_CV.py", label="Subir CV", icon=":material/arrow_forward:")

# ------------------------------------------------------------ cómo funciona
st.markdown('<p class="kicker">CÓMO FUNCIONA</p>', unsafe_allow_html=True)
cols = st.columns(len(STEPS))
for i, (col, (key, name, desc, path, done)) in enumerate(zip(cols, STEPS), start=1):
    with col.container(border=True, key=f"step_{key}"):
        head = f":green[:material/check_circle:] **{name}**" if done else f"**{i} · {name}**"
        if key == next_key and not done:
            head += " :orange-badge[Siguiente]"
        st.markdown(head)
        st.caption(desc)
        st.page_link(path, label="Abrir", icon=":material/arrow_forward:")

st.caption(":material/verified_user: Lazarus nunca se postula por ti. Usa el enlace de cada posición para postularte.")
