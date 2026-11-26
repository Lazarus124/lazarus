import pandas as pd
import streamlit as st

from lazarus.services import SOURCE_LABELS
from lazarus.ui import page, run_note, show_error

app = page("Vacantes", "📋")

if not app.active_cv():
    st.info("Suba un CV para calcular el score.")
    st.stop()

searches = app.searches()
if not searches:
    st.info("Todavía no hay búsquedas. Vaya a la página Buscar.")
    st.stop()

labels = {s["id"]: f"#{s['id']} · {s['keyword']} · {s['location'] or ''} {s['country'] or ''} · {s['jobs']} vacantes · {s['created_at'][:16]}"
          for s in searches}
labels = {None: "Todas las búsquedas", **labels}
default = st.session_state.get("search_id", searches[0]["id"])
keys = list(labels)
sid = st.selectbox("Búsqueda", keys, index=keys.index(default) if default in keys else 1, format_func=labels.get)

if sid and app.pending_count(sid):
    st.warning(f"{app.pending_count(sid)} vacantes sin analizar.")
    if st.button("Analizar ahora"):
        with st.spinner("Analizando..."):
            try:
                run_note(app.analyze(sid)["run_id"])
            except Exception as exc:  # noqa: BLE001
                show_error(exc, "El análisis falló")

rows = app.ranking(sid)
if not rows:
    st.info("No hay vacantes analizadas para esta búsqueda.")
    st.stop()

min_score = st.slider("Score mínimo", 0, 100, 0, 5)
rows = [r for r in rows if r["score"] >= min_score]

table = pd.DataFrame([{
    "Score": r["score"], "Puesto": r["title"], "Empresa": r["company"], "Ubicación": r["location"] or r["country"],
    "Modalidad": r["modality"], "Seniority": r["seniority"],
    "Fuente": SOURCE_LABELS.get(r["source"], r["source"]), "Enlace": r["url"],
} for r in rows])
st.dataframe(table, hide_index=True, use_container_width=True,
             column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
                            "Enlace": st.column_config.LinkColumn("Enlace", display_text="Abrir")})

st.subheader("Detalle")
for r in rows[:30]:
    b = r["breakdown"]
    with st.expander(f"{r['score']} · {r['title']} · {r['company'] or '—'}"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Skills requeridas", f"{b['required']}/60")
        c2.metric("Skills deseables", f"{b['nice']}/15")
        c3.metric("Seniority", f"{b['seniority']}/15")
        c4.metric("Ubicación", f"{b['location']}/10")
        if not b.get("required_listed"):
            st.caption("La vacante no lista skills requeridas: se usa un valor neutro.")
        st.markdown("**Coinciden:** " + (", ".join(f"`{s}`" for s in b["skills_matched"]) or "—"))
        st.markdown("**Faltan (requeridas):** " + (", ".join(f"`{s}`" for s in b["skills_missing_required"]) or "—"))
        if r["reasons"]:
            st.markdown("**Razones**\n" + "\n".join(f"- {x}" for x in r["reasons"]["reasons"]))
            if r["reasons"]["risks"]:
                st.markdown("**Riesgos**\n" + "\n".join(f"- {x}" for x in r["reasons"]["risks"]))
        elif st.button("Pedir razones a Claude", key=f"exp{r['match_id']}"):
            try:
                app.explain([r["match_id"]])
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                show_error(exc, "No se pudieron generar las razones")
        c1, c2 = st.columns(2)
        c1.link_button("Abrir la vacante original", r["url"])
        if c2.button("Escribir carta", key=f"carta{r['match_id']}"):
            st.session_state["letter_match_id"] = r["match_id"]
            st.switch_page("pages/4_Carta.py")
