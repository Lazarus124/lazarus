import pandas as pd
import streamlit as st

from lazarus import usage
from lazarus.ui import page

app = page("Configuración", "⚙️")

from lazarus.claude_client import health, resolve_binary
from lazarus.ui import claude_panel
from lazarus.secrets import scheme
from lazarus.services import BD_SOURCES, SOURCE_LABELS

st.subheader("Claves de API")
if scheme() == "dpapi":
    st.caption("Las claves se guardan cifradas con Windows (DPAPI). Solo su usuario de Windows puede leerlas. "
               "La app nunca muestra el valor guardado.")
else:
    st.warning("Este sistema no es Windows: las claves se guardan sin cifrar en la carpeta de datos (permisos 600).")

for name, label, help_url in (("firecrawl", "Firecrawl", "https://www.firecrawl.dev/app/api-keys"),
                               ("brightdata", "Bright Data", "https://brightdata.com/cp/setting/users")):
    src = app.key_source(name)
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        c1.markdown(f"**{label}** · " + {"interfaz": "✅ guardada", ".env": "✅ desde .env", None: "❌ falta"}[src])
        c1.caption(f"Obtenga la key en {help_url}")
        with c1.form(f"key_{name}", clear_on_submit=True):
            value = st.text_input("Nueva key", type="password", placeholder="Pegue la key aquí")
            if st.form_submit_button("Guardar") and value:
                try:
                    app.save_key(name, value)
                    st.session_state[f"keytest_{name}"] = app.test_key(name)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"No pude guardar la key: {exc}")
        if src:
            if c2.button("Probar", key=f"test_{name}"):
                st.session_state[f"keytest_{name}"] = app.test_key(name)
            if src == "interfaz" and c2.button("Borrar", key=f"del_{name}"):
                app.delete_key(name)
                st.session_state.pop(f"keytest_{name}", None)
                st.rerun()
        res = st.session_state.get(f"keytest_{name}")
        if res:
            (c2.success if res["ok"] else c2.warning if res["ok"] is None else c2.error)(res["message"])

st.subheader("Bright Data: datasets")
st.caption("Copie el dataset_id de cada scraper \"discover by keyword\" desde el panel de Bright Data. Vacío = fuente desactivada.")
with st.form("datasets"):
    values = {s: st.text_input(SOURCE_LABELS[s], app.cfg["brightdata"]["datasets"].get(s, ""), placeholder="gd_...")
              for s in BD_SOURCES}
    if st.form_submit_button("Guardar datasets"):
        for s, v in values.items():
            app.set_setting(f"dataset.{s}", v)
        st.success("Datasets guardados.")

st.subheader("Claude Code")
h = health(app.cfg["claude"]["binary"])
if h["ok"]:
    st.caption(f"Claude Code {h['version']} · {h['path']}")
    claude_panel(app, key="config")
else:
    st.error(h["error"])
if h.get("warning"):
    st.warning(h["warning"])
with st.form("claude_path"):
    path = st.text_input("Ruta de claude (opcional)", app.get_setting("claude.binary") or "",
                         placeholder=r"C:\Users\usuario\.local\bin\claude.exe",
                         help="Déjelo vacío para detectarla automáticamente.")
    if st.form_submit_button("Guardar ruta"):
        app.set_setting("claude.binary", path or "claude")
        st.session_state.pop("claude_health", None)
        st.rerun()

st.subheader("Consumo del mes")
for service, s in usage.status(app.db, app.cfg).items():
    st.write(f"{service}: {s['used']:,} de {s['limit']:,} ({s['ratio']:.0%})")

st.subheader("Modo debug")
debug = st.toggle("Guardar contenido completo de cada llamada en logs/debug/", value=app.log.debug,
                  help="Incluye el texto del CV. Úselo solo para diagnosticar un problema y desactívelo al terminar.")
if debug != app.log.debug:
    app.log.debug = debug
    st.rerun()

st.subheader("Dominios para Firecrawl")
domains = app.list_domains()
df = pd.DataFrame(domains)
edited = st.data_editor(
    df[["id", "host", "country", "enabled", "is_base"]], hide_index=True, use_container_width=True,
    disabled=["id", "host", "country", "is_base"],
    column_config={"enabled": st.column_config.CheckboxColumn("Activo"),
                   "is_base": st.column_config.CheckboxColumn("Base")})
if st.button("Guardar dominios"):
    for row in edited.itertuples():
        app.set_domain_enabled(int(row.id), bool(row.enabled))
    st.success("Dominios guardados.")

with st.form("nuevo_dominio", clear_on_submit=True):
    c1, c2 = st.columns([3, 1])
    host = c1.text_input("Agregar dominio", placeholder="ejemplo.com.mx")
    country = c2.text_input("País (ISO-2)", max_chars=2)
    if st.form_submit_button("Agregar") and host:
        try:
            app.add_domain(host, country)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

own = [d for d in domains if not d["is_base"]]
if own:
    labels = {d["id"]: d["host"] for d in own}
    rm = st.selectbox("Borrar un dominio propio", list(labels), format_func=labels.get)
    if st.button("Borrar"):
        app.delete_domain(rm)
        st.rerun()
