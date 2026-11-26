import streamlit as st

from lazarus.ui import page, run_note, show_error

app = page("CV", "📄")

up = st.file_uploader("Suba su CV", type=["pdf", "docx"])
if up and st.button("Procesar CV", type="primary"):
    with st.spinner("Leyendo el CV y extrayendo el perfil con Claude..."):
        try:
            res = app.upload_cv(up.name, up.getvalue())
            st.success("CV procesado y activado.")
            run_note(res["run_id"])
        except Exception as exc:  # noqa: BLE001
            show_error(exc, "No se pudo procesar el CV")

cv = app.active_cv()
if cv:
    st.subheader(f"CV activo: {cv['filename']}")
    p = cv["profile"]
    if p:
        c1, c2, c3 = st.columns(3)
        c1.metric("Seniority", p.get("seniority") or "—")
        c2.metric("Años de experiencia", p.get("years_experience") or "—")
        c3.metric("Skills", len(p.get("skills", [])))
        st.write(p.get("summary", ""))
        st.markdown("**Skills:** " + ", ".join(f"`{s}`" for s in p.get("skills", [])))
        st.markdown("**Idiomas:** " + ", ".join(p.get("languages", [])))
        st.markdown("**Roles:** " + ", ".join(p.get("roles", [])))
    with st.expander("Texto extraído"):
        st.text(cv["text"])

cvs = app.list_cvs()
if len(cvs) > 1:
    st.subheader("Versiones")
    labels = {c["id"]: f"{c['filename']} · {c['created_at'][:16]}" + (" (activo)" if c["active"] else "") for c in cvs}
    choice = st.selectbox("Activar otra versión", list(labels), format_func=labels.get)
    if st.button("Activar"):
        app.activate_cv(choice)
        st.rerun()
