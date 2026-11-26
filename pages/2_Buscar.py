import streamlit as st

from lazarus.services import ALL_SOURCES, SOURCE_LABELS
from lazarus.ui import page, run_note, show_error

app = page("Buscar", "🔍")
COUNTRIES = ["", "MX", "AR", "CO", "CL", "PE", "BR", "UY", "EC", "CR", "GT", "PA", "DO", "BO", "PY", "VE", "US"]

if not app.active_cv():
    st.info("Suba un CV primero para ver el ranking después de la búsqueda.")

status = app.source_status()
with st.form("buscar"):
    keyword = st.text_input("Rol o palabras clave", placeholder="devops junior")
    c1, c2 = st.columns(2)
    location = c1.text_input("Ciudad o región", placeholder="Guadalajara")
    country = c2.selectbox("País", COUNTRIES, format_func=lambda c: c or "Cualquiera")
    st.markdown("**Fuentes**")
    cols = st.columns(len(ALL_SOURCES))
    chosen = []
    for col, s in zip(cols, ALL_SOURCES):
        ok = status[s]["ok"]
        if col.checkbox(SOURCE_LABELS[s], value=ok, disabled=not ok, help=status[s]["why"] or None) and ok:
            chosen.append(s)
    force = st.checkbox("Buscar de nuevo aunque exista una búsqueda igual reciente", value=False)
    est = app.estimate(chosen)
    st.caption(f"Costo máximo estimado: Bright Data {est['brightdata']} registros · Firecrawl {est['firecrawl']} créditos")
    submitted = st.form_submit_button("Buscar", type="primary")

for s in ALL_SOURCES:
    if not status[s]["ok"]:
        st.caption(f"{SOURCE_LABELS[s]} desactivada: {status[s]['why']}")

if submitted:
    if not keyword.strip() or not chosen:
        st.warning("Escriba un rol y elija al menos una fuente.")
        st.stop()
    try:
        with st.status("Buscando vacantes...", expanded=True) as box:
            res = app.search(keyword, location, country, chosen, force=force)
            if res["reused"]:
                st.write("Uso los resultados de una búsqueda igual de las últimas horas.")
            for s, r in res["results"].items():
                if r["status"] == "ok":
                    st.write(f"✅ {SOURCE_LABELS[s]}: {r['found']} vacantes ({r['new']} nuevas)")
                elif r["status"] == "skipped":
                    st.write(f"⏭️ {SOURCE_LABELS[s]}: {r['message']}")
                else:
                    st.write(f"❌ {SOURCE_LABELS[s]}: {r['message']}")
            run_note(res["run_id"])
            sid = res["search_id"]
            st.session_state["search_id"] = sid
            pending = app.pending_count(sid)
            if pending:
                box.update(label=f"Analizando {pending} vacantes con Claude...")
                bar = st.progress(0.0)
                a = app.analyze(sid, progress=lambda i, n: bar.progress(i / n, text=f"{i} / {n}"))
                st.write(f"Análisis: {a['ok']} vacantes, {a['not_job']} páginas descartadas, "
                         f"{a['duplicates']} duplicadas, {a['failed']} con error.")
                run_note(a["run_id"])
            if app.active_cv():
                box.update(label="Escribiendo razones para las mejores vacantes...")
                e = app.explain_top(sid)
                run_note(e.get("run_id"))
            box.update(label="Búsqueda terminada", state="complete")
        st.page_link("pages/3_Vacantes.py", label="Ver el ranking", icon="➡️")
    except Exception as exc:  # noqa: BLE001
        show_error(exc, "La búsqueda falló")
