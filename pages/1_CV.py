import streamlit as st

from lazarus.ui import SENIORITY, page, run_note, show_error

app = page("Mi CV", "📄")

up = st.file_uploader("Suba su CV (PDF o Word)", type=["pdf", "docx"])
if up and st.button("Leer mi CV", type="primary"):
    with st.spinner("Leyendo su CV..."):
        try:
            res = app.upload_cv(up.name, up.getvalue())
            st.success("Listo. Lazarus usará este CV.")
            run_note(res["run_id"])
        except Exception as exc:  # noqa: BLE001
            show_error(exc, "No se pudo leer el CV")

cv = app.active_cv()
if cv:
    st.subheader(f"Lo que Lazarus entendió de su CV ({cv['filename']})")
    p = cv["profile"]
    if p:
        c1, c2, c3 = st.columns(3)
        c1.metric("Nivel", SENIORITY.get(p.get("seniority"), "Sin dato"))
        c2.metric("Años de experiencia", p.get("years_experience") or "—")
        c3.metric("Habilidades", len(p.get("skills", [])))
        st.write(p.get("summary", ""))
        st.markdown("**Habilidades:** " + ", ".join(f"`{s}`" for s in p.get("skills", [])))
        st.markdown("**Idiomas:** " + ", ".join(p.get("languages", [])))
        st.markdown("**Puestos:** " + ", ".join(p.get("roles", [])))
    with st.expander("Texto leído del CV"):
        st.text(cv["text"])

cvs = app.list_cvs()
if len(cvs) > 1:
    st.subheader("Otras versiones de su CV")
    labels = {c["id"]: f"{c['filename']} · {c['created_at'][:16]}" + (" (en uso)" if c["active"] else "") for c in cvs}
    choice = st.selectbox("Usar otra versión", list(labels), format_func=labels.get)
    if st.button("Usar esta versión"):
        app.activate_cv(choice)
        st.rerun()
