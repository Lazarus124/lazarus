"""RawJob -> Job: URLs canónicas, skills canónicas y duplicados."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
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
