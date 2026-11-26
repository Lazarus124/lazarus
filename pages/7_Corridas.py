import altair as alt
import pandas as pd
import streamlit as st

from lazarus.ui import page

app = page("Corridas", "🧭")

tab_hist, tab_det, tab_perf = st.tabs(["Historial", "Detalle", "Rendimiento"])

with tab_hist:
    c1, c2 = st.columns(2)
    kind = c1.selectbox("Tipo", [None, "search", "analyze", "explain", "cover_letter", "cv_upload", "cv_activate"],
                        format_func=lambda k: k or "Todos")
    status = c2.selectbox("Estado", [None, "ok", "error", "running"], format_func=lambda s: s or "Todos")
    runs = app.runs(kind=kind, status=status)
    if runs:
        df = pd.DataFrame(runs)
        df["id"] = df["run_id"].str[:8]
        st.dataframe(df[["started_at", "kind", "status", "duration_ms", "id", "error"]], hide_index=True,
                     use_container_width=True)
    else:
        st.info("Sin corridas.")

with tab_det:
    runs = app.runs(limit=300)
    if not runs:
        st.info("Sin corridas.")
    else:
        q = st.text_input("Buscar por run_id (o sus primeros 8 caracteres)", st.session_state.get("selected_run", "")[:8])
        matches = [r for r in runs if r["run_id"].startswith(q.strip())] if q.strip() else runs
        if not matches:
            st.warning("No encuentro esa corrida.")
            st.stop()
        labels = {r["run_id"]: f"{r['run_id'][:8]} · {r['kind']} · {r['status']} · {r['started_at'][:19]}" for r in matches}
        rid = st.selectbox("Corrida", list(labels), format_func=labels.get)
        run = next(r for r in matches if r["run_id"] == rid)
        c1, c2, c3 = st.columns(3)
        c1.metric("Estado", run["status"])
        c2.metric("Duración", f"{(run['duration_ms'] or 0) / 1000:.1f} s")
        c3.metric("Tipo", run["kind"])
        if run["error"]:
            st.error(run["error"])
        st.caption(f"Parámetros: {run['params_json']}")
        steps = app.run_steps(rid)
        if steps:
            sd = pd.DataFrame(steps)
            sd["start"] = pd.to_datetime(sd["started_at"])
            sd["end"] = sd["start"] + pd.to_timedelta(sd["duration_ms"], unit="ms")
            st.altair_chart(alt.Chart(sd).mark_bar().encode(
                x=alt.X("start:T", title="Inicio"), x2="end:T", y=alt.Y("name:N", title=None),
                color=alt.Color("status:N", scale=alt.Scale(domain=["ok", "error"], range=["#4C78A8", "#E45756"])),
                tooltip=["name", "status", "duration_ms", "error"]), use_container_width=True)
            for s in steps:
                icon = "❌" if s["status"] == "error" else "✅"
                with st.expander(f"{icon} {s['name']} · {s['duration_ms']} ms"):
                    if s["error"]:
                        st.error(s["error"])
                    st.json(s["data"])
        st.download_button("Exportar corrida (ZIP)", app.export_run(rid), file_name=f"corrida_{rid[:8]}.zip",
                           mime="application/zip")

with tab_perf:
    days = st.selectbox("Periodo", [1, 7, 30], index=1, format_func=lambda d: f"Últimos {d} días")
    perf = app.performance(days)
    if perf.empty:
        st.info("Sin datos todavía.")
    else:
        st.dataframe(perf, use_container_width=True)
        st.caption("p50: duración típica. p95: duración de los casos lentos.")
    cs = app.cache_stats(days)
    if cs["ratio"] is not None:
        st.metric("Aciertos de caché de Firecrawl", f"{cs['ratio']:.0%}", help=f"{cs['hits']} de {cs['hits'] + cs['scraped']} páginas")
    searches = app.db.query(
        "SELECT r.run_id, r.started_at, u.service, SUM(u.units) AS units FROM run r JOIN usage_log u ON u.run_id = r.run_id"
        " WHERE r.kind = 'search' GROUP BY r.run_id, u.service ORDER BY r.started_at DESC LIMIT 40")
    if searches:
        st.subheader("Consumo por búsqueda")
        sdf = pd.DataFrame(searches).pivot_table(index=["started_at", "run_id"], columns="service", values="units", fill_value=0)
        st.dataframe(sdf, use_container_width=True)
