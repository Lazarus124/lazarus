import streamlit as st

from lazarus.documents import prep_to_docx
from lazarus.ui import page, render_research, show_error, task_box, watch_tasks

app = page("Preparar entrevista", "🎯")

if not app.active_cv():
    st.info("Cargue su CV en **Mi CV**: la preparación se basa en su experiencia.")
    st.stop()

# ------------------------------------------------------------ elegir posición
st.subheader("¿Para qué posición se prepara?")
mode = st.radio("Origen", ["list", "link"], horizontal=True, label_visibility="collapsed",
                format_func=lambda m: "Una de mis posiciones recomendadas" if m == "list" else "Tengo el link de una posición")

job_id = st.session_state.get("interview_job")
if mode == "list":
    positions = app.positions_for_interview()
    if not positions:
        st.info("Todavía no hay posiciones. Busque empleo o use un link.")
        st.stop()
    labels = {p["job_id"]: (f"{p['score']} · " if p.get("score") is not None else "Agregada · ")
              + f"{p['title'] or 'Sin título'} · {p['company'] or '—'}" for p in positions}
    keys = list(labels)
    job_id = st.selectbox("Posición", keys, index=keys.index(job_id) if job_id in keys else 0, format_func=labels.get)
else:
    url = st.text_input("Link de la posición", placeholder="https://www.linkedin.com/jobs/view/... o el link de cualquier portal")
    key = f"url:{url.strip()}"
    watch_tasks(app, [key])
    state = task_box(app, key, "Leyendo la posición")
    t = app.worker.latest_for_key(key)
    if state == "done" and t and t.result:
        job_id = t.result
    elif state != "busy" and st.button("Agregar esta posición", type="primary", disabled=not url.strip()):
        app.worker.submit_call("Leyendo la posición", key, app.add_job_from_url, url.strip())
        st.rerun()
    if state != "done":
        st.caption("Lazarus lee la posición, la revisa y la compara con su CV. Los links de LinkedIn usan Bright Data; "
                   "los demás, Firecrawl.")
        st.stop()

st.session_state["interview_job"] = job_id
job = app.job_detail(job_id)
st.markdown(f"### {job['title'] or 'Posición'} · {job['company'] or ''}")
st.link_button("Ver la posición", job["url"])

watch_tasks(app, [f"prep:{job_id}", f"company:{job_id}"])

# ---------------------------------------------------------------- empresa
with st.expander("Sobre la empresa", expanded=False):
    research = app.get_company_research(job["company"])
    state = task_box(app, f"company:{job_id}", "Investigando la empresa")
    if research:
        render_research(research)
    if state != "busy" and job["company"]:
        st.caption("La guía usa esta investigación si existe. Conviene hacerla primero.")
        if st.button("Actualizar investigación" if research else "Averiguar más sobre la empresa"):
            app.worker.submit_call(f"Investigando {job['company']}", f"company:{job_id}", app.research_company, job_id)
            st.rerun()

# --------------------------------------------------------- proceso de entrevistas
st.subheader("Su proceso de entrevistas")
prep = app.get_interview_prep(job_id)
if prep and "stages" not in prep:
    st.warning("Esta guía es de una versión anterior (una sola entrevista). Vuelva a generarla para ver todas las etapas.")
    prep = None
state = task_box(app, f"prep:{job_id}", "Armando el plan del proceso")
if state != "busy":
    st.caption("Lazarus arma las etapas probables (reclutador/a, hiring manager, técnica, loop, dirección…) "
               "con preguntas para cada una. Después puede prepararse a fondo para la etapa que sigue.")
    if st.button("Volver a armar el plan" if prep else "Armar el plan de entrevistas", type="secondary" if prep else "primary"):
        app.worker.submit_call("Armando plan de entrevistas", f"prep:{job_id}", app.interview_prep, job_id)
        st.rerun()

if not prep:
    st.stop()

stages = app.interview_stages(job_id)
watch_tasks(app, [f"stage:{job_id}:{s['name']}" for s in stages])
st.write(prep.get("overview", ""))

# Progreso: qué etapas ya tuvo y cuál sigue
done = [s for s in stages if s["status"] == "hecha"]
nxt = next((s for s in stages if s["status"] != "hecha"), None)
st.progress(len(done) / len(stages) if stages else 0.0,
            text=f"{len(done)} de {len(stages)} etapas hechas" + (f" · Sigue: {nxt['name']}" if nxt else " · ¡Proceso completo!"))

names = [s["name"] for s in stages]
default = names.index(nxt["name"]) if nxt else 0
stage_name = st.radio("Etapa", names, index=default, horizontal=True,
                      format_func=lambda n: ("✅ " if any(s["name"] == n and s["status"] == "hecha" for s in stages) else "") + n)
stage = next(s for s in stages if s["name"] == stage_name)
plan = stage["plan"] or {}

with st.container(border=True):
    if plan:
        st.markdown(f"**Quién:** {plan['interviewer']} · **Formato:** {plan['format']}")
        st.markdown(f"**Objetivo:** {plan['goal']}")
        if plan.get("evaluates"):
            st.markdown("**Qué evalúan:** " + ", ".join(plan["evaluates"]))
    else:
        st.caption("Etapa agregada por usted.")

    tab_prep, tab_notes, tab_practice = st.tabs(["Preparación", "Mis notas de esta etapa", "Practicar"])
    with tab_prep:
        deep = stage["deep"]
        key = f"stage:{job_id}:{stage_name}"
        state = task_box(app, key, f"Preparando a fondo: {stage_name}")
        if state != "busy":
            if st.button("Volver a preparar a fondo" if deep else "Preparar a fondo esta etapa", key=f"deep_{stage_name}"):
                app.worker.submit_call(f"Preparando {stage_name}", key, app.prepare_stage, job_id, stage_name)
                st.rerun()
            st.caption("Usa las notas de las etapas que ya tuvo para profundizar donde más lo necesita.")
        if deep:
            st.markdown(f"**En qué enfocarse:** {deep['focus']}")
        questions = (deep or {}).get("questions") or plan.get("questions", [])
        for q in questions:
            with st.expander(q["question"]):
                st.markdown(f"**Por qué la preguntan:** {q['why']}")
                st.markdown(f"**Cómo responder:** {q['answer_hint']}")
                if q.get("follow_up"):
                    st.markdown(f"**Repregunta probable:** {q['follow_up']}")
        tips = (deep or {}).get("tips") or plan.get("tips", [])
        if tips:
            st.markdown("**Consejos**\n" + "\n".join(f"- {x}" for x in tips))
        ask = (deep or {}).get("questions_to_ask") or plan.get("questions_to_ask", [])
        if ask:
            st.markdown("**Preguntas para hacerle**\n" + "\n".join(f"- {x}" for x in ask))

    with tab_notes:
        with st.form(f"notes_{stage_name}"):
            status = st.radio("Estado", ["pendiente", "hecha"], horizontal=True,
                              index=1 if stage["status"] == "hecha" else 0,
                              format_func=lambda x: "Todavía no la tuve" if x == "pendiente" else "Ya la tuve")
            notes = st.text_area("Qué le preguntaron, cómo le fue, qué quedó pendiente", stage["notes"], height=150)
            if st.form_submit_button("Guardar"):
                app.save_stage(job_id, stage_name, status, notes)
                st.rerun()
        st.caption("Estas notas mejoran la preparación de las etapas siguientes.")

    with tab_practice:
        qs = [q["question"] for q in ((stage["deep"] or {}).get("questions") or plan.get("questions", []))]
        if not qs:
            st.info("Prepare esta etapa a fondo para tener preguntas para practicar.")
        else:
            question = st.selectbox("Pregunta", qs, key=f"pq_{stage_name}")
            answer = st.text_area("Su respuesta", height=180, key=f"pa_{stage_name}",
                                  placeholder="Responda como lo haría en la entrevista.")
            if st.button("Evaluar mi respuesta", disabled=not answer.strip(), key=f"pe_{stage_name}"):
                with st.spinner("Evaluando..."):
                    try:
                        st.session_state["feedback"] = (question, app.interview_feedback(job_id, question, answer, stage_name))
                    except Exception as exc:  # noqa: BLE001
                        show_error(exc, "No se pudo evaluar la respuesta")
            fb = st.session_state.get("feedback")
            if fb and fb[0] == question:
                f = fb[1]
                st.markdown(f"**Puntaje:** {'★' * f['score']}{'☆' * (5 - f['score'])}")
                if f.get("strengths"):
                    st.markdown("**Lo que estuvo bien**\n" + "\n".join(f"- {x}" for x in f["strengths"]))
                if f.get("improvements"):
                    st.markdown("**Para mejorar**\n" + "\n".join(f"- {x}" for x in f["improvements"]))
                st.markdown("**Una versión mejorada de su respuesta**")
                st.info(f.get("improved_answer", ""))

c1, c2 = st.columns([3, 1])
with c1.form("add_stage", clear_on_submit=True):
    a, b = st.columns([3, 1])
    new_stage = a.text_input("Agregar una etapa que no está", placeholder="Ejemplo: Entrevista con el CTO")
    b.write("")
    if b.form_submit_button("Agregar") and new_stage.strip():
        app.add_stage(job_id, new_stage)
        st.rerun()
c2.write("")
c2.download_button("Descargar el plan en Word", prep_to_docx(prep, f"{job['title']} · {job['company'] or ''}", stages),
                   file_name=f"Entrevistas_{(job['company'] or 'posicion').replace(' ', '_')}.docx",
                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

with st.expander("Temas para repasar y puntos para aclarar"):
    for label, items in (("Temas para repasar", prep.get("topics_to_review")), ("Puntos para aclarar en el proceso", prep.get("points_to_clarify"))):
        if items:
            st.markdown(f"**{label}**\n" + "\n".join(f"- {x}" for x in items))
