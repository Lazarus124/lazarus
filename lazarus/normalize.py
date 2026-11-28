"""RawJob -> Job: URLs canónicas, skills canónicas y duplicados."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .db import DB, now
from .models import RawJob

TRACKING_PARAMS = {"trk", "trackingid", "refid", "ref", "position", "pagenum", "src", "source",
                   "from", "sid", "originalsubdomain", "ebp", "eid", "currentjobid"}

SKILL_ALIASES = {
    "amazon web services": "aws",
    "aws cloud": "aws",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "microsoft azure": "azure",
    "k8s": "kubernetes",
    "js": "javascript",
    "node": "node.js",
    "nodejs": "node.js",
    "postgres": "postgresql",
    "english": "inglés",
    "ingles": "inglés",
    "portuguese": "portugués",
    "portugues": "portugués",
    "python3": "python",
    "ms excel": "excel",
    "microsoft excel": "excel",
    "ci/cd": "ci/cd",
    "terraform cloud": "terraform",
}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(query), ""))


def host_of(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


LEGAL_SUFFIXES = {"sa", "sa de cv", "de cv", "sapi de cv", "srl", "sas", "ltda", "spa", "inc", "llc", "ltd",
                  "sc", "s de rl de cv", "eireli", "me", "corp", "gmbh"}


def norm_text(s: str | None) -> str:
    if not s:
        return ""
    s = s.replace(".", "")  # "S.A." -> "SA", "Jr." -> "Jr"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def canon_skill(skill: str) -> str:
    s = re.sub(r"\s+", " ", skill.strip().lower())
    return SKILL_ALIASES.get(s, s)


def canon_skills(skills) -> list[str]:
    seen, out = set(), []
    for s in skills or []:
        c = canon_skill(s)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def norm_company(company: str | None) -> str:
    c = norm_text(company)
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        if c.endswith(" " + suffix):
            c = c[: -len(suffix) - 1].strip()
            break
    return c


def dedup_key(title: str | None, company: str | None, country: str | None) -> str | None:
    t, c = norm_text(title), norm_company(company)
    if not t or not c:
        return None
    raw = f"{t}|{c}|{norm_text(country)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def is_brightdata(source: str) -> bool:
    return not source.startswith("web:")


def insert_job(db: DB, rj: RawJob) -> tuple[int, bool]:
    """Guarda una vacante si su URL es nueva. Devuelve (job_id, es_nueva)."""
    url = canonical_url(rj.url)
    row = db.one("SELECT id FROM job WHERE url = ?", (url,))
    if row:
        return row["id"], False
    cur = db.execute(
        "INSERT INTO job (url, source, title, company, location, country, description, posted_at,"
        " fetched_at, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (url, rj.source, rj.title, rj.company, rj.location, rj.country, rj.description,
         rj.posted_at, now(), json.dumps(rj.raw, ensure_ascii=False, default=str)[:200_000]),
    )
    job_id = cur.lastrowid
    if rj.title and rj.company:
        assign_dedup(db, job_id, rj.title, rj.company, rj.country)
    return job_id, True


def insert_raw_jobs(db: DB, raw_jobs: list[RawJob], search_id: int) -> dict:
    """Guarda las vacantes de una búsqueda. Devuelve conteos. Dedup por URL al ingresar."""
    new, existing = 0, 0
    for rj in raw_jobs:
        job_id, is_new = insert_job(db, rj)
        new += is_new
        existing += not is_new
        db.execute("INSERT OR IGNORE INTO search_result (search_id, job_id) VALUES (?,?)", (search_id, job_id))
    return {"new": new, "existing": existing}


def assign_dedup(db: DB, job_id: int, title, company, country) -> int | None:
    """Calcula dedup_key y marca duplicados. Devuelve el id del original si este es duplicado."""
    key = dedup_key(title, company, country)
    if not key:
        return None
    db.execute("UPDATE job SET dedup_key = ? WHERE id = ?", (key, job_id))
    me = db.one("SELECT id, source FROM job WHERE id = ?", (job_id,))
    orig = db.one(
        "SELECT id, source FROM job WHERE dedup_key = ? AND duplicate_of IS NULL AND id != ? ORDER BY id LIMIT 1",
        (key, job_id),
    )
    if not orig:
        return None
    if is_brightdata(me["source"]) and not is_brightdata(orig["source"]):
        # Se conserva el registro de Bright Data: tiene datos más estructurados.
        db.execute("UPDATE job SET duplicate_of = ? WHERE id = ?", (job_id, orig["id"]))
        db.execute("UPDATE job SET duplicate_of = ? WHERE duplicate_of = ?", (job_id, orig["id"]))
        return None
    db.execute("UPDATE job SET duplicate_of = ? WHERE id = ?", (orig["id"], job_id))
    return orig["id"]


FRESHNESS_DAYS = {"day": 1, "3days": 3, "week": 7, "month": 30}
_UNITS = {"hora": 1 / 24, "hour": 1 / 24, "hr": 1 / 24, "minut": 0, "min": 0, "dia": 1, "día": 1, "day": 1,
          "semana": 7, "week": 7, "mes": 30, "month": 30}


def parse_posted(text: str | None, ref: date) -> str | None:
    """Fecha de publicación (AAAA-MM-DD) desde una fecha ISO o un texto relativo
    ("hace 3 días", "2 weeks ago", "ayer", "30+ days ago"). None si no se puede."""
    if not text:
        return None
    t = str(text).strip().lower()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    if t in ("hoy", "today", "just now", "recién", "recien") or "hoy" in t.split() or "today" in t:
        return ref.isoformat()
    if "ayer" in t or "yesterday" in t:
        return (ref - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*([a-záéíóú]+)", unicodedata.normalize("NFC", t))
    if m:
        n, unit = int(m[1]), m[2]
        for key, days in _UNITS.items():
            if unit.startswith(key):
                return (ref - timedelta(days=int(n * days))).isoformat()
    return None


def posted_on(job: dict, analysis: dict) -> str | None:
    """Fecha de publicación de una vacante: dato de la fuente o, si no, lo que leyó Claude."""
    try:
        ref = datetime.fromisoformat(job["fetched_at"]).date()
    except (KeyError, TypeError, ValueError):
        ref = date.today()
    found = parse_posted(job.get("posted_at"), ref)
    if found:
        return found
    days = analysis.get("posted_days_ago")
    if isinstance(days, int) and 0 <= days <= 365:
        return (ref - timedelta(days=days)).isoformat()
    return None


CLOSED_PATTERNS = [
    "ya no se aceptan solicitudes", "ya no acepta solicitudes", "ya no se reciben postulaciones",
    "esta vacante ya no esta disponible", "esta oferta ya no esta disponible", "esta oferta ya no esta activa",
    "la oferta ha expirado", "oferta finalizada", "vacante cerrada", "oferta cerrada", "proceso cerrado",
    "no longer accepting applications", "this job is no longer available", "job has expired",
    "position has been filled", "this job has expired", "vaga encerrada", "esta vaga nao esta mais disponivel",
]


def looks_closed(text: str | None) -> bool:
    """True si el texto dice que la posición ya no recibe postulaciones."""
    t = norm_text(text)
    return any(norm_text(p) in t for p in CLOSED_PATTERNS)
