import json
import pandas as pd
import streamlit as st

from lazarus.services import SOURCE_LABELS
from lazarus.documents import cv_to_docx
from lazarus.ui import (EMPLOYMENT, FRESHNESS, LEVEL_LABELS, MODALITY, SENIORITY, TRACK_LABELS, age_label, open_folder, page,
                        tracking_buttons, render_research, show_error, task_box, watch_tasks)

app = page("Vacantes recomendadas", "⭐")


def where(source: str) -> str:
    return source.split(":", 1)[1] if source.startswith("web:") else SOURCE_LABELS.get(source, source)


if not app.active_cv():
    st.info("Cargue su CV en **Mi CV** para ver qué ofertas le convienen.")
    st.stop()

searches = app.searches()
if not searches:
    st.info("Todavía no buscó empleo. Vaya a **Buscar empleo**.")
    st.stop()

def _work_label(s: dict) -> str:
    names = {"remote": "remoto", "hybrid": "híbrido", "onsite": "presencial"}
    parts = [names[m] for m in json.loads(s.get("modalities") or "[]")] + (["part time"] if s.get("part_time") else [])
    return (" · " + ", ".join(parts)) if parts else ""


labels = {s["id"]: f"{s['keyword']}{_work_label(s)}{' · ' + SENIORITY.get(s['level'], '') if s.get('level') else ''} · {s['location'] or ''} {s['country'] or ''} · {s['jobs']} ofertas · {s['created_at'][:16]}"
          for s in searches}
labels = {None: "Todas las búsquedas", **labels}
default = st.session_state.get("search_id", searches[0]["id"])
keys = list(labels)
sid = st.selectbox("Búsqueda", keys, index=keys.index(default) if default in keys else 1, format_func=labels.get)

@st.fragment(run_every=3)
def review_status(search_id: int) -> None:
    """Revisa en segundo plano las ofertas nuevas. Al terminar, actualiza la página."""
    t = app.worker.for_search(search_id)
    if t and t.active:
        st.info(f"{t.stage}: {t.done} de {t.total}. La lista se actualiza sola." if t.total
                else f"{t.stage}... La lista se actualiza sola.")
        st.session_state[f"was_active_{search_id}"] = True
    elif st.session_state.pop(f"was_active_{search_id}", False):
        st.rerun(scope="app")
    elif t and t.status == "error":
        st.error(f"{t.stage}: {t.error}")


if sid:
    pending = app.db.one(
        "SELECT COUNT(*) AS n FROM job j JOIN search_result sr ON sr.job_id = j.id"
        " WHERE sr.search_id = ? AND j.duplicate_of IS NULL AND j.analysis_status = 'pending'", (sid,))["n"]
    if pending:
        app.worker.submit_analysis(sid)  # no duplica si ya hay una revisión en curso
    review_status(sid)
    failed = app.pending_count(sid) - pending
    if failed and not (app.worker.for_search(sid) and app.worker.for_search(sid).active):
        if st.button(f"Reintentar {failed} ofertas que no se pudieron revisar"):
            app.db.execute("UPDATE job SET analysis_status = 'pending' WHERE analysis_status = 'failed'"
                           " AND id IN (SELECT job_id FROM search_result WHERE search_id = ?)", (sid,))
            app.worker.submit_analysis(sid)
            st.rerun()

search = next((s for s in searches if s["id"] == sid), None)
if sid:
    st.download_button("Descargar informe de esta búsqueda", app.export_search(sid),
                       file_name=f"lazarus_busqueda_{sid}.zip", mime="application/zip",
                       help="Archivo para enviar a soporte: qué se buscó, en qué fuentes, qué llegó y los errores.")
import json

from lazarus.normalize import FRESHNESS_DAYS

s_mod = json.loads((search or {}).get("modalities") or "[]")
WORK = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial"}
with st.expander("Filtros", icon=":material/tune:"):
    c1, c2 = st.columns(2)
    mods = c1.multiselect("Modalidad", list(WORK), default=s_mod, format_func=WORK.get, key=f"mods_{sid}",
                          placeholder="Todas")
    pt = c2.toggle("Solo part time", value=bool((search or {}).get("part_time")), key=f"pt_{sid}")
    unknown_mod = c2.toggle("Incluir posiciones sin dato de modalidad o jornada", value=True, key=f"um_{sid}",
                            disabled=not (mods or pt))
    c1, c2 = st.columns(2)
    fresh_default = (search or {}).get("freshness")
    fresh = c1.selectbox("Publicadas", list(FRESHNESS), index=list(FRESHNESS).index(fresh_default),
                         format_func=FRESHNESS.get, key=f"fresh_{sid}")
    undated = c2.toggle("Incluir posiciones sin fecha de publicación", value=True, disabled=fresh is None,
                        help="Algunos portales no muestran la fecha.")
    others, my_level = True, None
    c1, c2 = st.columns(2)
    if search and search["country"]:
        others = c1.toggle(f"Mostrar también ofertas de otros países (la búsqueda es para {search['country']})",
                           value=s_mod == ["remote"], help="En búsquedas solo remotas se muestran por defecto.")
    if search and search.get("level"):
        my_level = c2.toggle(f"Solo posiciones para mi nivel ({LEVEL_LABELS.get(search['level'], search['level'])})",
                             value=True, help="Oculta las posiciones de un nivel superior o que piden más años de "
                                              "experiencia que su CV.")
    c1, c2 = st.columns(2)
    show_closed = c1.toggle("Incluir posiciones cerradas", value=False,
                            help="Las que ya no reciben postulaciones (según la página o una verificación).")
    show_hidden = c2.toggle("Mostrar las que marqué como «No me gusta» u ocultas", value=False)
rows = app.ranking(sid, other_countries=others, my_level_only=my_level,
                   max_age_days=FRESHNESS_DAYS.get(fresh), include_undated=undated,
                   include_closed=show_closed, include_hidden=show_hidden,
                   modalities=mods or [], part_time_only=pt, include_unknown_modality=unknown_mod)
if not rows:
    st.info("Esta búsqueda todavía no tiene ofertas revisadas.")
    st.stop()

min_score = st.slider("Afinidad mínima", 0, 100, 0, 5, help="Qué tan bien encaja la oferta con su CV, de 0 a 100.")
rows = [r for r in rows if r["score"] >= min_score]

table = pd.DataFrame([{
    "Afinidad": r["score"], "Puesto": r["title"], "Empresa": r["company"], "Ubicación": r["location"] or r["country"],
    "Modalidad": MODALITY.get(r["modality"], "Sin dato"), "Jornada": EMPLOYMENT.get(r.get("employment_type"), "Sin dato"), "Nivel": SENIORITY.get(r["seniority"], "Sin dato"),
    "Publicada": age_label(r.get("posted_on")),
    "Estado": ("🔒 Cerrada · " if r.get("closed") else "") + TRACK_LABELS.get(r.get("tracking"), ""),
    "Publicada en": where(r["source"]), "Enlace": r["url"],
} for r in rows])
st.dataframe(table, hide_index=True, use_container_width=True,
             column_config={"Afinidad": st.column_config.ProgressColumn("Afinidad", min_value=0, max_value=100, format="%d"),
                            "Enlace": st.column_config.LinkColumn("Oferta", display_text="Ver oferta")})

st.subheader("Por qué le recomendamos cada posición")
watch_tasks(app, [k for r in rows[:30] for k in (f"company:{r['job_id']}", f"cv:{r['job_id']}", f"verify:{r['job_id']}")])

for r in rows[:30]:
    b = r["breakdown"]
    jid = r["job_id"]
    with st.expander(f"{r['score']} · {r['title']} · {r['company'] or '—'}"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Requisitos que cumple", f"{b['required']:.0f} de 60")
        c2.metric("Deseables que cumple", f"{b['nice']:.0f} de 15")
        c3.metric("Nivel de experiencia", f"{b['seniority']} de 15")
        c4.metric("Ubicación", f"{b['location']} de 10")
        if not b.get("required_listed"):
            st.caption("La posición no detalla requisitos: se usó un valor medio.")
        st.markdown("**Usted cumple:** " + (", ".join(f"`{s}`" for s in b["skills_matched"]) or "—"))
        st.markdown("**Le falta:** " + (", ".join(f"`{s}`" for s in b["skills_missing_required"]) or "—"))
        if r["reasons"]:
            st.markdown("**Por qué le conviene**\n" + "\n".join(f"- {x}" for x in r["reasons"]["reasons"]))
            if r["reasons"]["risks"]:
                st.markdown("**A tener en cuenta**\n" + "\n".join(f"- {x}" for x in r["reasons"]["risks"]))
        elif st.button("Explicar por qué", key=f"exp{r['match_id']}"):
            try:
                app.explain([r["match_id"]])
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                show_error(exc, "No se pudo generar la explicación")

        tracking_buttons(app, jid, r.get("tracking"), key=str(jid))
        saved = st.session_state.get(f"saved_{jid}")
        if saved:
            st.success("Guardé una copia para esta postulación:\n" + "\n".join(f"- {f}" for f in saved))
            if st.button("Abrir la carpeta de aplicaciones", key=f"open_{jid}"):
                open_folder(app.applications_dir())
        v1, v2 = st.columns([1, 3])
        if v1.button("Verificar si sigue abierta", key=f"ver_{jid}"):
            app.worker.submit_call("Verificando posición", f"verify:{jid}", app.verify_open, jid)
            st.rerun()
        vt = app.worker.latest_for_key(f"verify:{jid}")
        if vt and vt.active:
            v2.info("Verificando...")
        elif vt and vt.status == "done":
            (v2.warning if vt.result["closed"] else v2.success)(vt.result["reason"])
        elif vt and vt.status == "error":
            v2.error(vt.error)
        elif r.get("closed"):
            v2.warning("Esta posición parece cerrada.")

        c1, c2, c3, c4 = st.columns(4)
        c1.link_button("Ver la posición y postularme", r["url"], use_container_width=True)
        cv_busy = (t := app.worker.latest_for_key(f"cv:{jid}")) is not None and t.active
        cv_label = "Volver a preparar el CV" if app.get_tailored_cv(jid) else "Preparar CV para esta posición"
        if c2.button(cv_label, key=f"cvtop{jid}", use_container_width=True, disabled=cv_busy):
            app.worker.submit_call("Preparando CV", f"cv:{jid}", app.tailor_cv, jid)
            st.rerun()
        if c3.button("Escribir carta de presentación", key=f"carta{r['match_id']}", use_container_width=True):
            st.session_state["letter_match_id"] = r["match_id"]
            st.switch_page("pages/4_Carta.py")
        if c4.button("Preparar entrevista", key=f"int{jid}", use_container_width=True):
            st.session_state["interview_job"] = jid
            st.switch_page("pages/8_Entrevista.py")

        # ---- empresa
        st.markdown("---")
        research = app.get_company_research(r["company"])
        state = task_box(app, f"company:{jid}", f"Investigando {r['company'] or 'la empresa'}")
        if research:
            with st.container(border=True):
                render_research(research)
        if state != "busy" and r["company"]:
            if st.button("Actualizar investigación" if research else "Averiguar más sobre la empresa", key=f"co{jid}"):
                app.worker.submit_call(f"Investigando {r['company']}", f"company:{jid}", app.research_company, jid)
                st.rerun()
        elif not r["company"]:
            st.caption("La posición no indica la empresa: no se puede investigar.")

        # ---- CV a medida
        tailored = app.get_tailored_cv(jid)
        state = task_box(app, f"cv:{jid}", "Preparando su CV para esta posición")
        if tailored:
            with st.container(border=True):
                st.markdown(f"**CV para esta posición:** {tailored.get('headline', '')}")
                if tailored.get("notes_for_user"):
                    st.markdown("\n".join(f"- {n}" for n in tailored["notes_for_user"]))
                st.download_button("Descargar CV en Word", cv_to_docx(tailored), key=f"dlcv{jid}",
                                   file_name=f"CV_{(r['company'] or 'posicion').replace(' ', '_')}.docx",
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                st.caption("Revíselo antes de enviarlo. Se arma solo con datos de su CV.")
