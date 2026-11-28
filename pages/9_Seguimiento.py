import streamlit as st

from lazarus.ui import TRACK_LABELS, age_label, open_folder, page, tracking_buttons

app = page("Mis postulaciones", "📌")
st.caption("Las posiciones que marcó en **Vacantes recomendadas**. Las favoritas y las postuladas aparecen primero "
           "en **Preparar entrevista**.")

folder = app.applications_dir()
c1, c2 = st.columns([3, 1])
c1.markdown(f"Copias de sus postulaciones: `{folder}`")
if c2.button("Abrir carpeta", icon=":material/folder_open:"):
    if not open_folder(folder):
        st.info("La carpeta solo se puede abrir desde Windows.")

tabs = st.tabs([f"{TRACK_LABELS[s]} ({len(app.tracked([s]))})" for s in app.TRACK_STATUSES])
for tab, status in zip(tabs, app.TRACK_STATUSES):
    with tab:
        rows = app.tracked([status])
        if not rows:
            st.info("Todavía no hay posiciones aquí.")
        for r in rows:
            jid = r["job_id"]
            title = f"{r['title'] or 'Posición'} · {r['company'] or '—'}" + ("  🔒 cerrada" if r["closed"] else "")
            with st.expander(title):
                meta = []
                if r["score"] is not None:
                    meta.append(f"Afinidad {r['score']}")
                if r["applied_at"]:
                    meta.append(f"Se postuló: {age_label(r['applied_at'][:10]).lower()} ({r['applied_at'][:10]})")
                if meta:
                    st.caption(" · ".join(meta))
                tracking_buttons(app, jid, r["status"], key=f"seg_{status}_{jid}")
                notes = st.text_area("Notas", r["notes"], key=f"notes_{jid}_{status}",
                                     placeholder="Contacto, fecha de la entrevista, salario conversado…")
                c1, c2, c3 = st.columns(3)
                if c1.button("Guardar notas", key=f"sn_{jid}_{status}"):
                    app.save_notes(jid, notes)
                    st.success("Notas guardadas.")
                c2.link_button("Ver la posición", r["url"], use_container_width=True)
                if c3.button("Preparar entrevista", key=f"pi_{jid}_{status}", use_container_width=True):
                    st.session_state["interview_job"] = jid
                    st.switch_page("pages/8_Entrevista.py")
                if r["files"]:
                    st.markdown("**Copias guardadas:**\n" + "\n".join(f"- `{f}`" for f in r["files"]))
