"""Extrae texto de un CV en PDF o DOCX."""
from __future__ import annotations

import io


class CVParseError(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        text = _pdf(data)
    elif name.endswith(".docx"):
        text = _docx(data)
    else:
        raise CVParseError("Formato no soportado. Suba un PDF o un DOCX.")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if len(text) < 50:
        raise CVParseError("El archivo no tiene texto. Suba un DOCX o un PDF con texto (no escaneado).")
    return text


def _pdf(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)
