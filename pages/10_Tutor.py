"""Tutor Lazarus: plan de estudio para las habilidades que faltan, con recursos reales y chat."""
from datetime import date

import streamlit as st

from lazarus.ui import ICON, page, task_box, watch_tasks

app = page("Tutor Lazarus", "🦊")
st.caption("Lazarus arma un plan para aprender lo que piden las empresas y tu CV todavía no muestra. "
           "Solo recomienda videos y cursos que encontró en la web, nunca links inventados.")

TYPE_ICON = {"video": "▶️", "curso": "🎓", "documentacion": "📄", "practica": "🛠️", "proyecto": "🚀"}
LEVELS = {"cero": "Desde cero", "base": "Algo de base", "intermedio": "Intermedio"}
STYLES = ["Videos", "Lectura", "Práctica guiada", "Proyectos"]

plans = app.learning_plans()
watch_tasks(app, ["tutor:new"])
state = task_box(app, "tutor:new", "Lazarus está armando tu plan y buscando recursos (puede tardar unos minutos)")
if state == "done" and (t := app.worker.latest_for_key("tutor:new")) and not st.session_state.get(f"seen_{t.id}"):
    st.session_state[f"seen_{t.id}"] = True
    st.session_state["tutor_plan"] = t.result

labels = {p["id"]: f"{', '.join(s['skill'] for s in p['inputs']['skills'])[:70]} · {p['created_at'][:10]}" for p in plans}
c1, c2 = st.columns([3, 1])
choice = c1.selectbox("Tus planes", [None, *labels], format_func=lambda i: labels.get(i, "➕ Nuevo plan"),
                      index=([None, *labels].index(st.session_state["tutor_plan"])
                             if st.session_state.get("tutor_plan") in labels else (1 if plans else 0)))
yt = app.youtube.mode
c2.caption({"api": "🎬 Videos: YouTube conectado", "web": "🎬 Videos: búsqueda web",
            "none": "🎬 Sin búsqueda de videos: conecta YouTube o Firecrawl en Configuración"}[yt])

# ------------------------------------------------------------------ nuevo plan
if choice is None:
    if state == "busy":
        st.stop()
    cv = app.active_cv()
    if not cv:
        st.info("Primero carga tu CV en **Mi CV**: Lazarus lo usa para saber qué ya sabes.")
    with st.chat_message("assistant", avatar=ICON):
        st.write("¡Hola! Soy Lazarus. Antes de armar tu plan necesito saber qué quieres aprender y cómo te organizas.")

    st.markdown("#### 1. ¿Qué quieres aprender?")
    origin = st.radio("Origen", ["mercado", "posicion"], horizontal=True, label_visibility="collapsed",
                      format_func=lambda o: "Lo que pide el mercado" if o == "mercado" else "Lo que pide una posición")
    skills: list[str] = []
    label = ""
    job_id = None
    if origin == "mercado":
        gaps = app.market_gaps()
        if not gaps:
            st.info("Todavía no hay ofertas revisadas para comparar con tu CV. Haz una búsqueda o escribe la habilidad abajo.")
        opts = [g["skill"] for g in gaps]
        skills = st.multiselect("Habilidades que te faltan (de más a menos pedidas)", opts, default=opts[:3],
                                max_selections=5,
                                format_func=lambda s: next((f"{s} · {g['porcentaje']:.0f}% de las ofertas"
                                                            for g in gaps if g["skill"] == s), s))
        label = "Habilidades que pide el mercado en las ofertas revisadas y el CV no muestra."
    else:
        tracked = app.tracked(["favorito", "aplicado"])
        jobs = {r["job_id"]: f"{r['title'] or 'Posición'} · {r['company'] or ''}" for r in tracked}
        if not jobs:
            jobs = {r["job_id"]: f"{r['title'] or 'Posición'} · {r['company'] or ''}" for r in app.ranking()[:30]}
        if not jobs:
            st.info("No hay posiciones todavía. Busca empleo o marca favoritas en **Vacantes recomendadas**.")
        else:
            job_id = st.selectbox("Posición", list(jobs), format_func=jobs.get)
            opts = app.position_gaps(job_id)
            if not opts:
                st.success("Tu CV ya muestra todo lo obligatorio de esta posición. Puedes agregar algo abajo.")
            skills = st.multiselect("Habilidades que pide y tu CV no muestra", opts, default=opts[:5], max_selections=5)
            label = f"Habilidades que pide la posición {jobs[job_id]} y el CV no muestra."
    extra = st.text_input("¿Otra habilidad? (opcional)", placeholder="Por ejemplo: Kubernetes")
    if extra.strip() and extra.strip() not in skills:
        skills = [*skills, extra.strip()]

    if skills:
        with st.form("tutor_questions"):
            st.markdown("#### 2. Unas preguntas de Lazarus")
            levels = {}
            cols = st.columns(min(3, len(skills)))
            for i, s in enumerate(skills):
                levels[s] = cols[i % len(cols)].radio(f"Tu nivel en **{s}**", list(LEVELS), format_func=LEVELS.get,
                                                      key=f"lvl_{s}")
            hours = st.slider("¿Cuántas horas por semana puedes dedicarle?", 2, 30, 6)
            has_date = st.checkbox("Tengo una fecha objetivo (por ejemplo, una entrevista)")
            target = st.date_input("Fecha objetivo", min_value=date.today())
            styles = st.pills("¿Cómo aprendes mejor?", STYLES, selection_mode="multi", default=["Videos", "Práctica guiada"])
            if st.form_submit_button("Armar mi plan", type="primary"):
                inputs = {"skills": [{"skill": s, "level": LEVELS[levels[s]]} for s in skills], "hours": hours,
                          "target_date": target.isoformat() if has_date else None, "styles": styles or STYLES,
                          "origin": {"kind": origin, "label": label, "job_id": job_id}}
                app.worker.submit_call("Armando plan de estudio", "tutor:new", app.create_learning_plan, inputs)
                st.rerun()
    st.stop()

# ------------------------------------------------------------------ plan elegido
lp = app.get_learning_plan(choice)
plan, res, done = lp["plan"], lp["resources"], lp["done"]
tasks = [t for w in plan["weeks"] for t in w["tasks"]]
with st.chat_message("assistant", avatar=ICON):
    st.write(plan["intro"])
inp = lp["inputs"]
st.caption(f"{plan['total_weeks']} semanas · {inp['hours']} h por semana"
           + (f" · objetivo {inp['target_date']}" if inp.get("target_date") else "")
           + f" · {', '.join(s['skill'] + ' (' + s['level'].lower() + ')' for s in inp['skills'])}")
st.progress(len(done & {t["id"] for t in tasks}) / max(1, len(tasks)),
            text=f"Avance: {len(done & {t['id'] for t in tasks})} de {len(tasks)} tareas")
if not res:
    st.info("No encontré recursos verificados para este plan. Usa las búsquedas sugeridas o pídele videos a Lazarus en el chat.")

tab_plan, tab_chat = st.tabs(["Plan", "Chat con Lazarus"])
with tab_plan:
    for w in plan["weeks"]:
        wdone = sum(t["id"] in done for t in w["tasks"])
        with st.expander(f"Semana {w['week']} · {w['title']} ({wdone}/{len(w['tasks'])})",
                         expanded=wdone < len(w["tasks"]) and w is next(
                             (x for x in plan["weeks"] if any(t["id"] not in done for t in x["tasks"])), None)):
            st.markdown(f"**Objetivo:** {w['goal']} · {w['hours']:g} h")
            for t in w["tasks"]:
                new = st.checkbox(f"{TYPE_ICON.get(t['type'], '•')} {t['title']} · {t['hours']:g} h",
                                  value=t["id"] in done, key=f"task_{choice}_{t['id']}")
                if new != (t["id"] in done):
                    app.set_task_done(choice, t["id"], new)
                    st.rerun()
                for r in res.get(t["id"], []):
                    meta = " · ".join(x for x in (r.get("channel"), r.get("duration"),
                                                  f"{r['views']:,} vistas".replace(",", ".") if r.get("views") else None,
                                                  r.get("published")) if x)
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;🔗 [{r['title'] or r['url']}]({r['url']})"
                                + (f" — {meta}" if meta else "") + (f"  \n&nbsp;&nbsp;&nbsp;&nbsp;_{r['why']}_" if r.get("why") else ""))
                if t.get("search_query") and not res.get(t["id"]):
                    st.caption(f"Búsqueda sugerida: {t['search_query']}")
            st.markdown(f"✅ **Para cerrar la semana:** {w['checkpoint']}")
    st.markdown("#### 🚀 Proyecto final")
    st.markdown(f"**{plan['project']['title']}** — {plan['project']['description']}  \n"
                f"Entregable: {plan['project']['deliverable']}")
    if plan["certifications"]:
        st.markdown("#### 🏅 Certificaciones que suman")
        for c in plan["certifications"]:
            st.markdown(f"- **{c['name']}** ({c['skill']}): {c['why']}")
    if plan["tips"]:
        st.markdown("#### 💡 Consejos de Lazarus")
        for tip in plan["tips"]:
            st.markdown(f"- {tip}")

with tab_chat:
    key = f"tutor:chat:{choice}"
    watch_tasks(app, [key])
    for m in app.tutor_messages(choice):
        with st.chat_message("assistant" if m["role"] == "lazarus" else "user",
                             avatar=ICON if m["role"] == "lazarus" else None):
            st.markdown(m["content"])
            for v in m["videos"]:
                st.markdown(f"▶️ [{v['title']}]({v['url']})"
                            + (f" — {v['channel']}" if v.get("channel") else "")
                            + (f" · {v['duration']}" if v.get("duration") else ""))
    chat_state = task_box(app, key, "Lazarus está pensando")
    msg = st.chat_input("Pregúntale a Lazarus: una duda, que te explique algo o que te recomiende videos",
                        disabled=chat_state == "busy")
    if msg:
        app.worker.submit_call("Chat con el tutor", key, app.tutor_chat, choice, msg)
        st.rerun()
