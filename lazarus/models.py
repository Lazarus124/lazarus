"""Tipos de datos compartidos."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawJob:
    source: str              # "linkedin" | "indeed" | "glassdoor" | "web:<host>"
    url: str
    description: str         # texto o markdown completo
    title: str | None = None
    company: str | None = None
    location: str | None = None
    country: str | None = None  # ISO-2 si la fuente lo da
    posted_at: str | None = None
    raw: dict = field(default_factory=dict)


class SourceError(Exception):
    """Error de una fuente de vacantes (Bright Data o Firecrawl)."""
