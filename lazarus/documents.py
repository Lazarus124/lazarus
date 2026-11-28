"""Documentos Word: CV adaptado y guía de entrevista."""
from __future__ import annotations

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ACCENT = RGBColor(0x1F, 0x4E, 0x79)


def _base() -> Document:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    for s in doc.sections:
        s.left_margin = s.right_margin = s.top_margin = s.bottom_margin = Pt(54)
    return doc


def _heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(text.upper())
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = ACCENT
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)


def _bullets(doc: Document, items) -> None:
    for it in items:
        if it:
            doc.add_paragraph(str(it), style="List Bullet")


def _save(doc: Document) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def cv_to_docx(cv: dict) -> bytes:
    doc = _base()
    p = doc.add_paragraph()
    r = p.add_run(cv.get("name", ""))
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = ACCENT
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if cv.get("headline"):
        r = doc.add_paragraph().add_run(cv["headline"])
        r.font.size = Pt(12)
    if cv.get("contact"):
        r = doc.add_paragraph().add_run(cv["contact"])
        r.font.size = Pt(9)
    if cv.get("summary"):
        _heading(doc, "Perfil")
        doc.add_paragraph(cv["summary"])
    if cv.get("skills"):
        _heading(doc, "Habilidades")
        doc.add_paragraph(" · ".join(cv["skills"]))
    if cv.get("experience"):
        _heading(doc, "Experiencia")
        for e in cv["experience"]:
            p = doc.add_paragraph()
            p.add_run(f"{e.get('role', '')} — {e.get('company', '')}").bold = True
            if e.get("dates"):
                p.add_run(f"   {e['dates']}").italic = True
            _bullets(doc, e.get("bullets", []))
    if cv.get("education"):
        _heading(doc, "Formación")
        for e in cv["education"]:
            p = doc.add_paragraph()
            p.add_run(e.get("title", "")).bold = True
            p.add_run(f" — {e.get('institution', '')}  {e.get('dates', '')}")
    if cv.get("certifications"):
        _heading(doc, "Certificaciones")
        _bullets(doc, cv["certifications"])
    if cv.get("languages"):
        _heading(doc, "Idiomas")
        doc.add_paragraph(" · ".join(cv["languages"]))
    return _save(doc)


def prep_to_docx(prep: dict | None, title: str, stages: list[dict]) -> bytes:
    """Guía del proceso de entrevistas: una sección por etapa elegida, con su preparación si existe."""
    prep = prep or {}
    doc = _base()
    r = doc.add_paragraph().add_run(f"Proceso de entrevistas: {title}")
    r.bold = True
    r.font.size = Pt(16)
    r.font.color.rgb = ACCENT
    if prep.get("overview"):
        doc.add_paragraph(prep["overview"])
    for i, stage in enumerate(stages, 1):
        st, deep = stage.get("plan") or {}, stage.get("deep") or {}
        _heading(doc, f"Etapa {i}: {stage['name']}")
        if st:
            doc.add_paragraph(f"Quién: {st['interviewer']} · Formato: {st['format']}")
            doc.add_paragraph(f"Objetivo: {st['goal']}")
            if st.get("evaluates"):
                doc.add_paragraph("Evalúan: " + ", ".join(st["evaluates"]))
        if stage.get("notes"):
            doc.add_paragraph(f"Mis notas: {stage['notes']}")
        if deep.get("focus"):
            doc.add_paragraph(f"En qué enfocarse: {deep['focus']}")
        questions = deep.get("questions") or st.get("questions", [])
        if not questions:
            doc.add_paragraph("Todavía sin preparar.").runs[0].italic = True
        for q in questions:
            doc.add_paragraph().add_run(q["question"]).bold = True
            doc.add_paragraph(f"Por qué la preguntan: {q['why']}")
            doc.add_paragraph(f"Cómo responder: {q['answer_hint']}")
            if q.get("follow_up"):
                doc.add_paragraph(f"Repregunta probable: {q['follow_up']}")
        for label, key in (("Consejos", "tips"), ("Preguntas para hacerle", "questions_to_ask")):
            items = deep.get(key) or st.get(key)
            if items:
                doc.add_paragraph().add_run(label).italic = True
                _bullets(doc, items)
    for name, items in (("Temas para repasar", prep.get("topics_to_review", [])),
                        ("Puntos para aclarar en el proceso", prep.get("points_to_clarify", []))):
        if items:
            _heading(doc, name)
            _bullets(doc, items)
    return _save(doc)
