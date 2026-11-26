"""Carta de presentación: texto editable y exportación a DOCX."""
from __future__ import annotations

import io


def to_text(letter: dict) -> str:
    parts = [letter.get("greeting", "").strip(), *[p.strip() for p in letter.get("paragraphs", [])],
             letter.get("closing", "").strip()]
    return "\n\n".join(p for p in parts if p)


def to_docx_bytes(body: str) -> bytes:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for block in body.split("\n\n"):
        block = block.strip()
        if block:
            doc.add_paragraph(block)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
