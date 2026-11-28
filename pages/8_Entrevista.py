import streamlit as st

from lazarus.documents import prep_to_docx
from lazarus.services import CATALOG_BY_NAME, DEFAULT_STAGES, STAGE_CATALOG
from lazarus.ui import page, render_research, show_error, task_box, watch_tasks

app = page("Preparar entrevista", "🎯")

if not app.active_cv():
    st.info("Cargue su CV en **Mi CV**: la preparación se basa en su experiencia.")
    st.stop()

# ------------------------------------------------------------ elegir posición
st.subheader("¿Para qué posición se prepara?")
mode = st.radio("Origen", ["tracked", "list", "link"], horizontal=True, label_visibility="collapsed",
                format_func={"tracked": "Mis favoritas y postulaciones", "list": "Todas las recomendadas",
                             "link": "Tengo el link de una posición"}.get)

job_id = st.session_state.get("interview_job")
if mode in ("tracked", "list"):
    positions = app.positions_for_interview(only_tracked=mode == "tracked")
    if not positions:
        st.info("Todavía no marcó favoritas ni postulaciones. Hágalo en **Vacantes recomendadas**, "
                "o elija «Todas las recomendadas»." if mode == "tracked" else
                "Todavía no hay posiciones. Busque empleo o use un link.")
        st.stop()
    icon = {"favorito": "⭐ ", "aplicado": "✅ "}
    labels = {p["job_id"]: icon.get(p.get("status"), "") + (f"{p['score']} · " if p.get("score") is not None else "")
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

watch_tasks(app, [f"company:{job_id}"])

# ---------------------------------------------------------------- empresa
with st.expander("Sobre la empresa", expanded=False):
    research = app.get_company_research(job["company"])
    state = task_box(app, f"company:{job_id}", "Investigando la empresa")
    if research:
        render_research(research)
    if state != "busy" and job["company"]:
        st.caption("La preparación usa esta investigación si existe. Conviene hacerla primero.")
        if st.button("Actualizar investigación" if research else "Averiguar más sobre la empresa"):
            app.worker.submit_call(f"Investigando {job['company']}", f"company:{job_id}", app.research_company, job_id)
            st.rerun()

# --------------------------------------------------------- proceso de entrevistas
st.subheader("Su proceso de entrevistas")
prep = app.get_interview_prep(job_id)  # guías de versiones anteriores: se usan si existen
if prep and "stages" not in prep:
    prep = None
stages = app.interview_stages(job_id)
current = [s["name"] for s in stages]

with st.expander("1. ¿Qué etapas tiene su proceso?", expanded=not stages):
    st.caption("Marque las etapas que tiene o espera tener. Pase el mouse por el ícono ⓘ para ver de qué se trata cada una. "
               "Puede cambiarlas cuando quiera: las etapas con notas o preparación no se pierden.")
    with st.form(f"stages_{job_id}"):
        options = [c["name"] for c in STAGE_CATALOG] + [n for n in current if n not in CATALOG_BY_NAME]
        cols = st.columns(3)
        chosen = []
        for i, name in enumerate(options):
            c = CATALOG_BY_NAME.get(name)
            help_text = (f"{c['interviewer']} · {c['format']}. {c['goal']}. Evalúa: {', '.join(c['evaluates'])}."
                         if c else "Etapa agregada por usted.")
            default = name in current if stages else name in DEFAULT_STAGES
            if cols[i % 3].checkbox(name, value=default, help=help_text, key=f"stg_{job_id}_{name}"):
                chosen.append(name)
        other = st.text_input("Otra etapa (opcional)", placeholder="Ejemplo: Entrevista con el cliente")
        if st.form_submit_button("Guardar etapas", type="primary"):
            if other.strip():
                chosen.append(other.strip())
            if not chosen:
                st.error("Elija al menos una etapa.")
            else:
                kept = app.set_stages(job_id, chosen)
                if kept:
                    st.session_state["stages_kept"] = kept
                st.rerun()
    if st.session_state.pop("stages_kept", None):
        st.info("Algunas etapas desmarcadas tienen notas o preparación y se conservaron.")

if not stages:
    st.stop()

stage_keys = {s["name"]: f"stage:{job_id}:{s['name']}" for s in stages}
watch_tasks(app, list(stage_keys.values()))
busy = {n for n, k in stage_keys.items() if (t := app.worker.latest_for_key(k)) and t.active}
prepared = {s["name"] for s in stages if s["deep"] or (s["plan"] or {}).get("questions")}

# Progreso: qué etapas ya tuvo y cuál sigue
done = [s for s in stages if s["status"] == "hecha"]
nxt = next((s for s in stages if s["status"] != "hecha"), None)
st.progress(len(done) / len(stages),
            text=f"{len(done)} de {len(stages)} etapas hechas" + (f" · Sigue: {nxt['name']}" if nxt else " · ¡Proceso completo!"))

with st.container(border=True):
    st.markdown("**2. ¿Qué quiere preparar?**")
    pending = [s["name"] for s in stages if s["name"] not in busy]
    default = [n for n in ([nxt["name"]] if nxt else []) if n in pending and n not in prepared]
    to_prep = st.multiselect("Etapas para preparar", pending, default=default, label_visibility="collapsed",
                             format_func=lambda n: n + (" · ya preparada" if n in prepared else ""),
                             placeholder="Elija una o más etapas")
    if st.button("Preparar las elegidas", type="primary", disabled=not to_prep):
        for n in to_prep:
            app.worker.submit_call(f"Preparando {n}", stage_keys[n], app.prepare_stage, job_id, n)
        st.rerun()
    st.caption("Lazarus prepara cada etapa por separado, con preguntas, consejos y preguntas para hacerle. "
               "Usa sus notas de las etapas que ya tuvo para profundizar donde más lo necesita.")
    if busy:
        st.info("Preparando: " + ", ".join(sorted(busy)) + ". Puede seguir usando Lazarus.")

if prep and prep.get("overview"):
    st.write(prep["overview"])

names = [s["name"] for s in stages]
def _mark(n):
    s = next(x for x in stages if x["name"] == n)
    return ("✅ " if s["status"] == "hecha" else "⏳ " if n in busy else "📝 " if n in prepared else "") + n
stage_name = st.radio("Etapa", names, index=names.index(nxt["name"]) if nxt else 0, horizontal=True, format_func=_mark)
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
            if stage_name not in prepared:
                st.info("Esta etapa todavía no está preparada.")
            if st.button("Volver a preparar" if stage_name in prepared else "Preparar esta etapa",
                         key=f"deep_{stage_name}", type="secondary" if stage_name in prepared else "primary"):
                app.worker.submit_call(f"Preparando {stage_name}", key, app.prepare_stage, job_id, stage_name)
                st.rerun()
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
            st.info("Prepare esta etapa para tener preguntas para practicar.")
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

st.download_button("Descargar la preparación en Word", prep_to_docx(prep, f"{job['title']} · {job['company'] or ''}", stages),
                   file_name=f"Entrevistas_{(job['company'] or 'posicion').replace(' ', '_')}.docx",
                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

if prep and (prep.get("topics_to_review") or prep.get("points_to_clarify")):
    with st.expander("Temas para repasar y puntos para aclarar"):
        for label, items in (("Temas para repasar", prep.get("topics_to_review")), ("Puntos para aclarar en el proceso", prep.get("points_to_clarify"))):
            if items:
                st.markdown(f"**{label}**\n" + "\n".join(f"- {x}" for x in items))
