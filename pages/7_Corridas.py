import altair as alt
import pandas as pd
import streamlit as st

from lazarus.ui import RUN_KINDS, RUN_STATUS, page

app = page("Actividad y diagnóstico", "🧭")
st.caption("Registro de todo lo que hizo Lazarus. Sirve para entender un error o pedir ayuda.")

tab_hist, tab_det, tab_perf = st.tabs(["Historial", "Detalle de una acción", "Rendimiento"])

with tab_hist:
    c1, c2 = st.columns(2)
    kind = c1.selectbox("Tipo", [None, *RUN_KINDS], format_func=lambda k: RUN_KINDS.get(k, "Todas"))
    status = c2.selectbox("Resultado", [None, *RUN_STATUS], format_func=lambda s: RUN_STATUS.get(s, "Todos"))
    runs = app.runs(kind=kind, status=status)
    if runs:
        df = pd.DataFrame(runs)
        view = pd.DataFrame({
            "Fecha (UTC)": df["started_at"].str[:19].str.replace("T", " "),
            "Acción": df["kind"].map(lambda k: RUN_KINDS.get(k, k)),
            "Resultado": df["status"].map(lambda s: RUN_STATUS.get(s, s)),
            "Duración (s)": (df["duration_ms"].fillna(0) / 1000).round(1),
            "Código de referencia": df["run_id"].str[:8],
            "Error": df["error"].fillna(""),
        })
        st.dataframe(view, hide_index=True, use_container_width=True)
    else:
        st.info("Todavía no hay actividad.")

with tab_det:
    runs = app.runs(limit=300)
    if not runs:
        st.info("Todavía no hay actividad.")
    else:
        q = st.text_input("Código de referencia", st.session_state.get("selected_run", "")[:8])
        matches = [r for r in runs if r["run_id"].startswith(q.strip())] if q.strip() else runs
        if not matches:
            st.warning("No encuentro ese código.")
            st.stop()
        labels = {r["run_id"]: f"{r['run_id'][:8]} · {RUN_KINDS.get(r['kind'], r['kind'])} · {RUN_STATUS.get(r['status'], r['status'])} · {r['started_at'][:19]}" for r in matches}
        rid = st.selectbox("Acción", list(labels), format_func=labels.get)
        run = next(r for r in matches if r["run_id"] == rid)
        c1, c2, c3 = st.columns(3)
        c1.metric("Resultado", RUN_STATUS.get(run["status"], run["status"]))
        c2.metric("Duración", f"{(run['duration_ms'] or 0) / 1000:.1f} s")
        c3.metric("Acción", RUN_KINDS.get(run["kind"], run["kind"]))
        if run["error"]:
            st.error(run["error"])
        st.caption(f"Datos de la acción: {run['params_json']}")
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
        st.download_button("Descargar informe para soporte (ZIP)", app.export_run(rid), file_name=f"corrida_{rid[:8]}.zip",
                           mime="application/zip")

with tab_perf:
    days = st.selectbox("Periodo", [1, 7, 30], index=1, format_func=lambda d: f"Últimos {d} días")
    perf = app.performance(days)
    if perf.empty:
        st.info("Todavía no hay datos.")
    else:
        st.dataframe(perf, use_container_width=True)
        st.caption("p50: duración típica (ms). p95: duración de los casos más lentos (ms).")
    cs = app.cache_stats(days)
    if cs["ratio"] is not None:
        st.metric("Páginas reutilizadas sin costo", f"{cs['ratio']:.0%}", help=f"{cs['hits']} de {cs['hits'] + cs['scraped']} páginas")
    searches = app.db.query(
        "SELECT r.run_id, r.started_at, u.service, SUM(u.units) AS units FROM run r JOIN usage_log u ON u.run_id = r.run_id"
        " WHERE r.kind = 'search' GROUP BY r.run_id, u.service ORDER BY r.started_at DESC LIMIT 40")
    if searches:
        st.subheader("Uso del plan por búsqueda")
        sdf = pd.DataFrame(searches).pivot_table(index=["started_at", "run_id"], columns="service", values="units", fill_value=0)
        st.dataframe(sdf, use_container_width=True)
