from datetime import datetime, timedelta, timezone

import altair as alt
import streamlit as st

from lazarus import metrics
from lazarus.ui import MODALITY, SENIORITY, page

app = page("Qué pide el mercado", "📊")
st.caption("Se calcula con las ofertas de sus búsquedas. No representa todo el mercado.")

searches = app.searches()
c1, c2, c3 = st.columns(3)
countries = sorted({r["country"] for r in app.db.query("SELECT DISTINCT country FROM job_analysis WHERE country IS NOT NULL")})
country = c1.selectbox("País", [None, *countries], format_func=lambda c: c or "Todos")
slabels = {None: "Todas", **{s["id"]: f"{s['keyword']} · {s['created_at'][:10]}" for s in searches}}
sid = c2.selectbox("Búsqueda", list(slabels), format_func=slabels.get)
days = c3.selectbox("Periodo", [None, 7, 30, 90], format_func=lambda d: f"Últimos {d} días" if d else "Todo")
since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds") if days else None

df = metrics.load_frame(app.db, country=country, search_id=sid, since=since)
n = len(df)
st.metric("Ofertas analizadas", n)
if n == 0:
    st.info("No hay ofertas revisadas con estos filtros.")
    st.stop()
if n < app.cfg["metrics"]["min_salary_n"]:
    st.warning("Son pocas ofertas: tome estos datos con cautela.")

st.subheader("Habilidades más pedidas")
kind = st.radio("Tipo", ["required", "nice"], horizontal=True, format_func=lambda k: "Obligatorias" if k == "required" else "Deseables")
top = metrics.top_skills(df, kind)
if not top.empty:
    st.altair_chart(alt.Chart(top).mark_bar().encode(
        x=alt.X("porcentaje:Q", title="% de ofertas que la piden"), y=alt.Y("skill:N", sort="-x", title=None),
        tooltip=["skill", "vacantes", "porcentaje"]), use_container_width=True)

st.subheader("Lo que piden y su CV no muestra")
cv = app.active_cv()
if cv:
    g = metrics.gap(df, cv["profile"].get("skills", []), app.cfg["metrics"]["gap_threshold"])
    if g.empty:
        st.success("Su CV muestra todo lo que piden al menos 1 de cada 5 ofertas.")
    else:
        st.dataframe(g.rename(columns={"skill": "Habilidad", "vacantes": "Ofertas", "porcentaje": "% de ofertas"}), hide_index=True, use_container_width=True)
else:
    st.info("Cargue su CV en **Mi CV** para ver esta comparación.")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Nivel de experiencia por país")
    st.bar_chart(metrics.distribution(df, "seniority").rename(columns=SENIORITY))
with c2:
    st.subheader("Modalidad por país")
    st.bar_chart(metrics.distribution(df, "modality").rename(columns=MODALITY))

st.subheader("Sueldos publicados")
sal = metrics.salaries(df, app.cfg["metrics"]["min_salary_n"])
if sal.empty:
    st.info("Ninguna de estas ofertas publica sueldo.")
else:
    st.dataframe(sal.rename(columns={"n": "ofertas", "p25": "sueldo bajo", "mediana": "sueldo típico", "p75": "sueldo alto"}).replace({"periodo": {"month": "mensual", "year": "anual", "hour": "por hora"}}), hide_index=True, use_container_width=True)
    st.caption("Se usa el punto medio del rango de cada oferta, sin convertir monedas. "
               f"Con menos de {app.cfg['metrics']['min_salary_n']} ofertas no se calcula (\"{metrics.INSUFFICIENT}\").")
