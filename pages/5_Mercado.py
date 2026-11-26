from datetime import datetime, timedelta, timezone

import altair as alt
import streamlit as st

from lazarus import metrics
from lazarus.ui import page

app = page("Mercado", "📊")
st.caption("Los datos vienen solo de sus búsquedas. No representan todo el mercado.")

searches = app.searches()
c1, c2, c3 = st.columns(3)
countries = sorted({r["country"] for r in app.db.query("SELECT DISTINCT country FROM job_analysis WHERE country IS NOT NULL")})
country = c1.selectbox("País", [None, *countries], format_func=lambda c: c or "Todos")
slabels = {None: "Todas", **{s["id"]: f"#{s['id']} · {s['keyword']}" for s in searches}}
sid = c2.selectbox("Búsqueda", list(slabels), format_func=slabels.get)
days = c3.selectbox("Periodo", [None, 7, 30, 90], format_func=lambda d: f"Últimos {d} días" if d else "Todo")
since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds") if days else None

df = metrics.load_frame(app.db, country=country, search_id=sid, since=since)
n = len(df)
st.metric("Vacantes en la muestra (n)", n)
if n == 0:
    st.info("No hay vacantes analizadas con estos filtros.")
    st.stop()
if n < app.cfg["metrics"]["min_salary_n"]:
    st.warning("Muestra pequeña: las conclusiones pueden no ser confiables.")

st.subheader("Top skills")
kind = st.radio("Tipo", ["required", "nice"], horizontal=True, format_func=lambda k: "Requeridas" if k == "required" else "Deseables")
top = metrics.top_skills(df, kind)
if not top.empty:
    st.altair_chart(alt.Chart(top).mark_bar().encode(
        x=alt.X("porcentaje:Q", title="% de vacantes"), y=alt.Y("skill:N", sort="-x", title=None),
        tooltip=["skill", "vacantes", "porcentaje"]), use_container_width=True)

st.subheader("Brecha CV vs mercado")
cv = app.active_cv()
if cv:
    g = metrics.gap(df, cv["profile"].get("skills", []), app.cfg["metrics"]["gap_threshold"])
    if g.empty:
        st.success("Su CV cubre las skills que piden 20 % o más de estas vacantes.")
    else:
        st.dataframe(g, hide_index=True, use_container_width=True)
else:
    st.info("Suba un CV para ver la brecha.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Seniority por país")
    st.bar_chart(metrics.distribution(df, "seniority"))
with c2:
    st.subheader("Modalidad por país")
    st.bar_chart(metrics.distribution(df, "modality"))

st.subheader("Salarios publicados")
sal = metrics.salaries(df, app.cfg["metrics"]["min_salary_n"])
if sal.empty:
    st.info("Ninguna vacante de la muestra publica salario.")
else:
    st.dataframe(sal, hide_index=True, use_container_width=True)
    st.caption("Punto medio del rango de cada vacante. Sin conversión de monedas. "
               f"Con menos de {app.cfg['metrics']['min_salary_n']} vacantes se muestra \"{metrics.INSUFFICIENT}\".")
