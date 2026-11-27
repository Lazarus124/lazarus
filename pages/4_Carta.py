import streamlit as st

from lazarus.letters import to_docx_bytes
from lazarus.ui import page, run_note, show_error

app = page("Carta de presentación", "✉️")

rows = app.ranking()
if not rows:
    st.info("Todavía no hay ofertas recomendadas. Vaya a **Buscar empleo**.")
    st.stop()

options = {r["match_id"]: f"{r['score']} · {r['title']} · {r['company'] or '—'}" for r in rows}
keys = list(options)
default = st.session_state.get("letter_match_id", keys[0])
mid = st.selectbox("Oferta", keys, index=keys.index(default) if default in keys else 0, format_func=options.get)
st.session_state["letter_match_id"] = mid

langs = {None: "El idioma de la oferta", "es": "Español", "pt": "Portugués", "en": "Inglés"}
lang = st.selectbox("Idioma", list(langs), format_func=langs.get)

if st.button("Generar carta", type="primary"):
    with st.spinner("Escribiendo la carta..."):
        try:
            res = app.generate_letter(mid, lang)
            st.session_state[f"letter_{mid}"] = res["letter_id"]
            run_note(res["run_id"])
        except Exception as exc:  # noqa: BLE001
            show_error(exc, "No se pudo generar la carta")

letters = app.letters_for(mid)
if letters:
    current_id = st.session_state.get(f"letter_{mid}", letters[0]["id"])
    current = next((x for x in letters if x["id"] == current_id), letters[0])
    body = st.text_area("Su carta (puede editarla)", current["body_md"], height=420, key=f"body_{current['id']}")
    c1, c2 = st.columns(2)
    if c1.button("Guardar cambios"):
        app.save_letter(current["id"], body)
        st.success("Cambios guardados.")
    c2.download_button("Descargar en Word", to_docx_bytes(body), file_name=f"carta_{mid}.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.caption("Revise la carta antes de enviarla. Se escribe solo con datos de su CV, pero puede tener errores.")
    if len(letters) > 1:
        with st.expander(f"Versiones anteriores ({len(letters) - 1})"):
            for x in letters[1:]:
                st.markdown(f"**{x['created_at'][:16]} · {x['language']}**")
                st.text(x["body_md"])
