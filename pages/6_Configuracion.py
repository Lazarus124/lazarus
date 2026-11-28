import streamlit as st

from lazarus import __version__, usage
from lazarus.claude_client import health
from lazarus.secrets import scheme
from lazarus.services import BD_SOURCES, SOURCE_LABELS
from lazarus.ui import SERVICE_LABELS, claude_panel, page

app = page("Configuración", "⚙️")

# ------------------------------------------------------------------ conexiones
st.subheader("Conexiones para buscar empleo")
if scheme() == "dpapi":
    st.caption("Las claves se guardan cifradas en esta computadora. Solo su usuario de Windows puede leerlas.")
else:
    st.warning("En este sistema las claves se guardan sin cifrar.")

CONNECTIONS = (
    ("brightdata", "Bright Data", "Busca en LinkedIn, Indeed y Glassdoor.", "https://brightdata.com/cp/setting/users"),
    ("firecrawl", "Firecrawl", "Busca en portales de empleo de la región.", "https://www.firecrawl.dev/app/api-keys"),
    ("youtube", "YouTube (opcional)", "El tutor Lazarus recomienda videos con vistas, duración y fecha. "
     "Sin esta clave, Lazarus busca videos en la web con Firecrawl.",
     "https://console.cloud.google.com/apis/library/youtube.googleapis.com (active la API y cree una clave en Credenciales)"),
)
for name, label, what, url in CONNECTIONS:
    src = app.key_source(name)
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        c1.markdown(f"**{label}** — {what}")
        c1.caption(("✅ Conectado" if src else "❌ Falta conectar") + f" · Obtenga su clave en {url}")
        with c1.form(f"key_{name}", clear_on_submit=True):
            value = st.text_input("Clave", type="password", placeholder="Pegue la clave aquí")
            if st.form_submit_button("Guardar") and value:
                try:
                    app.save_key(name, value)
                    st.session_state[f"keytest_{name}"] = app.test_key(name)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"No pude guardar la clave: {exc}")
        if src:
            if c2.button("Probar", key=f"test_{name}"):
                st.session_state[f"keytest_{name}"] = app.test_key(name)
            if src == "interfaz" and c2.button("Quitar", key=f"del_{name}"):
                app.delete_key(name)
                st.session_state.pop(f"keytest_{name}", None)
                st.rerun()
        res = st.session_state.get(f"keytest_{name}")
        if res:
            (c2.success if res["ok"] else c2.warning if res["ok"] is None else c2.error)(res["message"])

# ---------------------------------------------------------------------- claude
st.subheader("Asistente de IA (Claude)")
h = health(app.cfg["claude"]["binary"])
if h["ok"]:
    claude_panel(app, key="config")
else:
    st.error("Falta instalar Claude.")
    st.link_button("Descargar Claude", "https://claude.com/download")

# ------------------------------------------------------------------------- uso
st.subheader("Uso del plan este mes")
for service, s in usage.status(app.db, app.cfg).items():
    st.progress(min(s["ratio"], 1.0), text=f"{SERVICE_LABELS[service]}: {s['ratio']:.0%} usado")

# ------------------------------------------------------------ aplicaciones
st.subheader("Carpeta de aplicaciones")
st.markdown("Al marcar **Me postulé**, Lazarus guarda aquí una copia del CV (y de la carta, si la escribió) "
            "con el nombre de la empresa y la posición.")
with st.form("apps_dir"):
    new_dir = st.text_input("Carpeta", str(app.applications_dir()))
    if st.form_submit_button("Guardar"):
        app.set_setting("applications_dir", new_dir.strip())
        st.success("Carpeta guardada.")

# ------------------------------------------------------------------ apariencia
st.subheader("Apariencia")
st.markdown("Lazarus usa el modo claro u oscuro de Windows. Para elegirlo a mano, abra el menú **⋮** "
            "(arriba a la derecha) y elija **Light** (claro), **Dark** (oscuro) o **System** (el de Windows).")

# -------------------------------------------------------------------- avanzado
with st.expander("Avanzado"):
    st.markdown("**Fuentes de Bright Data**")
    st.caption("Identificador de cada buscador de Bright Data (\"dataset_id\", empieza con gd_). "
               "Se copia del panel de Bright Data. Vacío = esa fuente queda apagada.")
    with st.form("datasets"):
        values = {s: st.text_input(SOURCE_LABELS[s], app.cfg["brightdata"]["datasets"].get(s, ""), placeholder="gd_...")
                  for s in BD_SOURCES}
        if st.form_submit_button("Guardar"):
            for s, v in values.items():
                app.set_setting(f"dataset.{s}", v)
            st.success("Guardado.")

    st.markdown("**Ubicación de Claude**")
    if h["ok"]:
        st.caption(f"Versión {h['version']} · {h['path']}")
    if h.get("warning"):
        st.warning(h["warning"])
    with st.form("claude_path"):
        path = st.text_input("Ruta del programa (opcional)", app.get_setting("claude.binary") or "",
                             placeholder=r"C:\Users\usuario\.local\bin\claude.exe",
                             help="Déjelo vacío para que Lazarus la encuentre solo.")
        if st.form_submit_button("Guardar ruta"):
            app.set_setting("claude.binary", path or "claude")
            st.session_state.pop("claude_health", None)
            st.rerun()

    st.markdown("**Diagnóstico detallado**")
    debug = st.toggle("Guardar el detalle completo de cada consulta a Claude", value=app.log.debug,
                      help="Solo para resolver un problema. Incluye el texto de su CV. Desactívelo al terminar.")
    if debug != app.log.debug:
        app.log.debug = debug
        st.rerun()

    st.caption(f"Lazarus {__version__} · Datos en {app.cfg['paths']['data']}")
