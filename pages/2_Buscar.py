import pandas as pd
import streamlit as st

from lazarus.services import ALL_SOURCES, BD_SOURCES, COUNTRY_NAMES, SOURCE_LABELS, WEB
from lazarus.ui import page

app = page("Buscar empleo", "🔍")
COUNTRIES = {"": "Cualquiera", **COUNTRY_NAMES}


def why_empty(diag: dict) -> str:
    """Explica en palabras simples por qué una fuente no trajo ofertas."""
    if not diag:
        return ""
    if diag.get("records", 0) == 0:
        return " La fuente no encontró resultados para esta búsqueda."
    parts = []
    if diag.get("errors"):
        parts.append(f"{diag['errors']} resultados con error ({', '.join(diag.get('error_samples', []))})")
    if diag.get("unmapped"):
        parts.append(f"{diag['unmapped']} resultados que Lazarus no pudo leer")
    return (" " + "; ".join(parts) + ". El detalle está en Actividad y diagnóstico.") if parts else ""

if not app.active_cv():
    st.info("Cargue su CV en **Mi CV** para ver qué ofertas le convienen después de buscar.")

# ------------------------------------------------------------------ qué busca
st.subheader("Qué busca")
keyword = st.text_input("Puesto o palabras clave", placeholder="Ejemplo: soporte cloud junior")
c1, c2 = st.columns(2)
location = c1.text_input("Ciudad o región (opcional)", placeholder="Ejemplo: Guadalajara")
country = c2.selectbox("País", list(COUNTRIES), format_func=COUNTRIES.get)
remote = st.toggle("Solo trabajos remotos", help="Busca ofertas 100 % remotas. Se muestran también las de empresas de otros países.")

# ---------------------------------------------------------------- dónde buscar
st.subheader("Dónde buscar")
status = app.source_status()
chosen = []
cols = st.columns(len(ALL_SOURCES))
for col, s in zip(cols, ALL_SOURCES):
    ok = status[s]["ok"]
    if col.checkbox(SOURCE_LABELS[s], value=ok, disabled=not ok, key=f"src_{s}", help=status[s]["why"] or None) and ok:
        chosen.append(s)
off = [s for s in ALL_SOURCES if not status[s]["ok"]]
if off:
    st.caption(" · ".join(f"{SOURCE_LABELS[s]}: {status[s]['why']}" for s in off))

domains = app.list_domains()
active = [d for d in domains if d["enabled"]]
all_portals = st.session_state.get("portal_scope") == "todos"
in_country = [d for d in active if all_portals or not country or not d["country"] or d["country"] == country]
with st.expander(f"Portales de empleo de la región · se usarán {len(in_country)} de {len(active)} activos"):
    a, b = st.columns(2)
    scope = a.radio("Qué portales usar", ["pais", "todos"], horizontal=False, key="portal_scope",
                    format_func=lambda k: f"Los de {COUNTRIES.get(country) or 'cualquier país'} y los regionales" if k == "pais"
                    else "Todos los portales activos")
    all_portals = scope == "todos"
    max_pages = b.slider("Cuántas ofertas leer de los portales", 5, 50, app.cfg["firecrawl"]["max_scrapes"], 5,
                         help="Más ofertas = más resultados, pero usa más del plan mensual.")
    st.caption("Desmarque un portal para no usarlo nunca. Agregue portales que conozca al final de la lista.")
    df = pd.DataFrame(domains)[["id", "host", "country", "enabled", "is_base"]]
    df["country"] = df["country"].map(lambda c: COUNTRIES.get(c, c) if c else "Regional")
    edited = st.data_editor(
        df, hide_index=True, use_container_width=True, disabled=["id", "host", "country", "is_base"],
        column_order=["enabled", "host", "country"],
        column_config={"enabled": st.column_config.CheckboxColumn("Usar"),
                       "host": st.column_config.TextColumn("Portal"),
                       "country": st.column_config.TextColumn("País")},
        key="domains_editor")
    changed = {int(r.id): bool(r.enabled) for r in edited.itertuples()
               if bool(r.enabled) != bool(df.loc[df["id"] == r.id, "enabled"].iloc[0])}
    if changed and st.button("Guardar cambios de portales"):
        for domain_id, enabled in changed.items():
            app.set_domain_enabled(domain_id, enabled)
        st.rerun()

    with st.form("nuevo_portal", clear_on_submit=True):
        a, b, c = st.columns([3, 2, 1])
        host = a.text_input("Agregar un portal", placeholder="ejemplo.com.mx")
        new_country = b.selectbox("País del portal", list(COUNTRIES), format_func=lambda k: COUNTRIES[k] if k else "Regional")
        c.write("")
        if c.form_submit_button("Agregar") and host:
            try:
                app.add_domain(host, new_country)
                st.rerun()
            except ValueError:
                st.error("Escriba solo el dominio del portal, por ejemplo: ejemplo.com.mx")

    own = [d for d in domains if not d["is_base"]]
    if own:
        labels = {d["id"]: d["host"] for d in own}
        a, b = st.columns([3, 1])
        rm = a.selectbox("Quitar un portal que agregó", list(labels), format_func=labels.get)
        if b.button("Quitar"):
            app.delete_domain(rm)
            st.rerun()

# ---------------------------------------------------------------------- buscar
est = app.estimate(chosen, max_pages)
plan = app.cfg["usage"]
parts = []
if any(s in BD_SOURCES for s in chosen):
    parts.append(f"hasta {est['brightdata'] / plan['brightdata_monthly']:.1%} del plan mensual de LinkedIn, Indeed y Glassdoor")
if WEB in chosen:
    parts.append(f"hasta {est['firecrawl'] / plan['firecrawl_monthly']:.1%} del plan mensual de portales")
if parts:
    st.caption("Esta búsqueda usa " + " y ".join(parts) + ".")
force = st.checkbox("Buscar de nuevo aunque hice esta misma búsqueda hace poco", value=False)

if st.button("Buscar", type="primary"):
    if not keyword.strip() or not chosen:
        st.warning("Escriba un puesto y elija al menos un lugar donde buscar.")
        st.stop()
    st.session_state["search_task"] = app.worker.submit_search(
        keyword=keyword, location=location, country=country, sources=chosen, force=force,
        all_portals=all_portals, max_pages=max_pages, remote=remote)


@st.fragment(run_every=2)
def search_progress(task_id: str) -> None:
    """Avance de la búsqueda. La búsqueda sigue aunque cambie de página."""
    t = app.worker.get(task_id)
    if not t:
        return
    with st.container(border=True):
        if t.active:
            st.markdown(f"**{t.stage}...** Puede ir a otras páginas: la búsqueda sigue en segundo plano.")
            st.progress(t.done / t.total if t.total else 0.0, text=f"{t.done} de {t.total}" if t.total else None)
        elif t.status == "error":
            st.error(f"{t.stage}: {t.error}" + (f"\n\nCódigo de referencia: `{t.run_id[:8]}`" if t.run_id else ""))
            if t.auth_error:
                st.session_state["claude_auth"] = {"supported": True, "logged_in": False, "email": None}
                st.page_link("pages/0_Inicio.py", label="Iniciar sesión en Claude", icon="🔑")
        else:
            st.success("Búsqueda terminada.")
        if t.summary.get("reused"):
            st.write("Uso los resultados de la misma búsqueda que hizo hace poco.")
        for s, r in t.results.items():
            if r["status"] == "ok":
                msg = f"{SOURCE_LABELS[s]}: {r['found']} ofertas ({r['new']} nuevas)."
                if r["found"] == 0:
                    msg += why_empty(r.get("diag", {}))
                st.write(("✅ " if r["found"] else "⚠️ ") + msg)
            elif r["status"] == "skipped":
                st.write(f"⏭️ {SOURCE_LABELS[s]}: {r['message']}")
            else:
                st.write(f"❌ {SOURCE_LABELS[s]}: no se pudo buscar ({r['message']})")
        a = t.summary.get("analysis")
        if a:
            st.write(f"Revisión: {a['ok']} ofertas útiles, {a['not_job']} páginas que no eran ofertas, "
                     f"{a['duplicates']} repetidas, {a['failed']} que no se pudieron revisar.")
        if not t.active and t.search_id:
            st.session_state["search_id"] = t.search_id
            c1, c2 = st.columns(2)
            c1.page_link("pages/3_Vacantes.py", label="Ver las vacantes recomendadas", icon="➡️")
            c2.download_button("Descargar informe de esta búsqueda", app.export_search(t.search_id),
                               file_name=f"lazarus_busqueda_{t.search_id}.zip", mime="application/zip",
                               key=f"dl_{t.id}")


if st.session_state.get("search_task"):
    search_progress(st.session_state["search_task"])
