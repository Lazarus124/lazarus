"""Bright Data Web Scraper API: LinkedIn Jobs, Indeed y Glassdoor.

Flujo asíncrono: trigger -> progress -> snapshot.
IMPORTANTE: el mapeo de campos se basa en la documentación. Verifíquelo con una
respuesta real y guarde esa respuesta en tests/fixtures/.
"""
from __future__ import annotations

import re
import time

import httpx

from ..models import RawJob, SourceError
from ..runlog import Run

API = "https://api.brightdata.com/datasets/v3"

# Nivel de experiencia de Lazarus -> filtro "experience_level" de LinkedIn.
LINKEDIN_LEVEL = {"intern": "Internship", "junior": "Entry level", "mid": "Associate",
                  "senior": "Mid-Senior level", "lead": "Director"}

# Modalidad de Lazarus -> filtro "remote" de LinkedIn (acepta un solo valor).
LINKEDIN_MODALITY = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}
# Palabra que se agrega a la búsqueda en fuentes sin filtro de modalidad (Indeed, Glassdoor, portales).
MODALITY_WORD = {"remote": ("remoto", "remote"), "hybrid": ("híbrido", "hybrid")}

# Frescura de Lazarus -> filtro "time_range" de LinkedIn (no tiene "3 días": se usa la semana y Lazarus filtra).
LINKEDIN_TIME = {"day": "Past 24 hours", "3days": "Past week", "week": "Past week", "month": "Past month"}

# Bright Data exige "location" en LinkedIn, Indeed y Glassdoor. Sin ciudad se usa el país (en inglés, sin acentos).
COUNTRY_EN = {"MX": "Mexico", "AR": "Argentina", "CO": "Colombia", "CL": "Chile", "PE": "Peru", "BR": "Brazil",
              "UY": "Uruguay", "EC": "Ecuador", "CR": "Costa Rica", "GT": "Guatemala", "PA": "Panama",
              "DO": "Dominican Republic", "BO": "Bolivia", "PY": "Paraguay", "VE": "Venezuela", "US": "United States"}

# Campos candidatos en orden de preferencia, por fuente.
FIELD_MAP = {
    "linkedin": {
        "url": ["url", "job_url", "apply_link"],
        "title": ["job_title", "title"],
        "company": ["company_name", "company"],
        "location": ["job_location", "location"],
        "country": ["country_code", "country"],
        "description": ["job_summary", "job_description_formatted", "job_description", "description"],
        "posted_at": ["job_posted_date", "job_posted_time", "date_posted"],
    },
    "indeed": {
        "url": ["url", "job_url", "link"],
        "title": ["job_title", "title"],
        "company": ["company_name", "company"],
        "location": ["location", "job_location"],
        "country": ["country", "country_code"],
        "description": ["description_text", "description", "job_description"],
        "posted_at": ["date_posted", "date_posted_parsed"],
    },
    "glassdoor": {
        "url": ["url", "job_url", "job_link"],
        "title": ["job_title", "title"],
        "company": ["company_name", "company"],
        "location": ["job_location", "location"],
        "country": ["country", "country_code"],
        "description": ["job_overview", "description", "job_description"],
        "posted_at": ["job_posting_date", "date_posted"],
    },
}


def _first(record: dict, keys: list[str]):
    for k in keys:
        v = record.get(k)
        if v not in (None, "", []):
            return v
    return None


def _clean_html(text: str) -> str:
    text = re.sub(r"<(br|/p|/li|/h\d)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def map_record(source: str, record: dict) -> RawJob | None:
    fm = FIELD_MAP[source]
    url = _first(record, fm["url"])
    desc = _first(record, fm["description"])
    if not url or not desc:
        return None
    title = _first(record, fm["title"])
    company = _first(record, fm["company"])
    if isinstance(company, dict):
        company = company.get("name")
    country = _first(record, fm["country"])
    return RawJob(
        source=source,
        url=str(url),
        title=str(title) if title else None,
        company=str(company) if company else None,
        location=str(_first(record, fm["location"]) or "") or None,
        country=str(country).upper()[:2] if country and len(str(country)) <= 3 else None,
        description=_clean_html(str(desc)),
        posted_at=str(_first(record, fm["posted_at"]) or "") or None,
        raw=record,
    )


class BrightDataSource:
    def __init__(self, api_key: str, cfg: dict, client: httpx.Client | None = None, sleep=time.sleep):
        self.api_key = api_key
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=60)
        self.sleep = sleep

    def available(self, source: str) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Falta la clave de Bright Data (en Configuración)"
        if not self.cfg["datasets"].get(source):
            return False, f"Falta configurar {source.capitalize()} (Configuración → Avanzado)"
        return True, ""

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _check(self, resp: httpx.Response, what: str) -> None:
        if resp.status_code in (401, 403):
            raise SourceError(f"Bright Data: key inválida o sin permiso ({resp.status_code}) en {what}")
        if resp.status_code == 402:
            raise SourceError("Bright Data: saldo agotado (402)")
        if resp.status_code == 429:
            raise SourceError("Bright Data: límite de velocidad (429)")
        if resp.status_code >= 400:
            raise SourceError(f"Bright Data: HTTP {resp.status_code} en {what}: {resp.text[:800]}")

    def build_input(self, source: str, keyword: str, location: str, country: str, remote: bool = False,
                    level: str | None = None, freshness: str | None = None,
                    modalities: list[str] | None = None, part_time: bool = False) -> dict:
        template = self.cfg.get("inputs", {}).get(source, {"keyword": "{keyword}", "location": "{location}"})
        cc = (country or "").upper()
        if remote and not modalities:
            modalities = ["remote"]
        single = modalities[0] if modalities and len(modalities) == 1 else None
        if single in MODALITY_WORD and not any("{remote}" in v for v in template.values()):
            # Indeed y Glassdoor no tienen filtro de modalidad: se agrega la palabra a la búsqueda.
            keyword = f"{keyword} {MODALITY_WORD[single][1 if cc == 'US' else 0]}"
        if part_time and not any("{job_type}" in v for v in template.values()):
            keyword = f"{keyword} part time"
        values = {"remote": LINKEDIN_MODALITY.get(single or "", ""), "job_type": "Part-time" if part_time else "",
                  "experience_level": LINKEDIN_LEVEL.get(level or "", ""),
                  "time_range": LINKEDIN_TIME.get(freshness or "", ""),
                  "keyword": keyword, "location": location.strip() or COUNTRY_EN.get(cc, "Latin America"), "country": cc,
                  # Indeed usa un dominio por país: mx.indeed.com, ar.indeed.com; Estados Unidos usa indeed.com
                  "indeed_domain": "indeed.com" if cc in ("", "US") else f"{cc.lower()}.indeed.com"}
        return {k: v.format(**values) for k, v in template.items() if v.format(**values) != ""}

    def _wait_snapshot(self, snapshot_id: str, st) -> httpx.Response:
        deadline = time.monotonic() + self.cfg["poll_timeout_s"]
        polls = 0
        while True:
            polls += 1
            pr = self.client.get(f"{API}/progress/{snapshot_id}", headers=self._headers())
            self._check(pr, "progress")
            state = pr.json().get("status")
            if state == "ready":
                break
            if state == "failed":
                raise SourceError(f"Bright Data: el snapshot {snapshot_id} falló")
            if time.monotonic() > deadline:
                st.set(polls=polls)
                raise SourceError(f"Bright Data: tiempo agotado esperando {snapshot_id}")
            self.sleep(self.cfg["poll_interval_s"])
        st.set(polls=polls)
        sr = self.client.get(f"{API}/snapshot/{snapshot_id}", params={"format": "json"}, headers=self._headers())
        self._check(sr, "snapshot")
        return sr

    def collect_url(self, source: str, url: str, run: Run) -> RawJob | None:
        """Trae una sola posición por su URL (por ejemplo, un link de LinkedIn que pega el usuario)."""
        with run.step(f"brightdata.{source}.url") as st:
            params = {"dataset_id": self.cfg["datasets"][source], "include_errors": "true"}
            resp = self.client.post(f"{API}/trigger", params=params, json=[{"url": url}], headers=self._headers())
            self._check(resp, "trigger")
            snapshot_id = resp.json().get("snapshot_id")
            if not snapshot_id:
                raise SourceError(f"Bright Data: respuesta sin snapshot_id: {resp.text[:300]}")
            records = self._wait_snapshot(snapshot_id, st).json()
            if isinstance(records, dict):
                records = records.get("data") or [records]
            jobs = [j for j in (map_record(source, r) for r in records if isinstance(r, dict) and not r.get("error")) if j]
            st.set(records=len(records), mapped=len(jobs))
            return jobs[0] if jobs else None

    def search(self, source: str, keyword: str, location: str, country: str, run: Run,
               remote: bool = False, level: str | None = None, freshness: str | None = None,
               modalities: list[str] | None = None, part_time: bool = False) -> tuple[list[RawJob], int, dict]:
        """Devuelve (vacantes, registros cobrados, diagnóstico)."""
        with run.step(f"brightdata.{source}", keyword=keyword, location=location, country=country) as st:
            params = {
                "dataset_id": self.cfg["datasets"][source],
                "type": "discover_new",
                "discover_by": "keyword",
                "include_errors": "true",
                "limit_per_input": str(self.cfg["limit_per_source"]),
            }
            body = [self.build_input(source, keyword, location, country, remote, level, freshness, modalities, part_time)]
            st.set(input=body[0])
            resp = self.client.post(f"{API}/trigger", params=params, json=body, headers=self._headers())
            self._check(resp, "trigger")
            snapshot_id = resp.json().get("snapshot_id")
            if not snapshot_id:
                raise SourceError(f"Bright Data: respuesta sin snapshot_id: {resp.text[:300]}")
            st.set(snapshot_id=snapshot_id)
            sr = self._wait_snapshot(snapshot_id, st)
            records = sr.json()
            if isinstance(records, dict):
                records = records.get("data") or records.get("records") or []
            ok = [r for r in records if isinstance(r, dict) and not r.get("error")]
            jobs = [j for j in (map_record(source, r) for r in ok) if j]
            diag = {"records": len(records), "errors": len(records) - len(ok), "mapped": len(jobs)}
            bad = [r for r in records if isinstance(r, dict) and r.get("error")]
            if bad:  # motivo de los errores que informa Bright Data (sin datos personales)
                diag["error_samples"] = sorted({str(r.get("error_code") or r.get("error"))[:120] for r in bad})[:5]
            if ok and len(jobs) < len(ok):  # registros que no se pudieron leer: guardar solo los nombres de campos
                diag["unmapped"] = len(ok) - len(jobs)
                diag["sample_keys"] = sorted(ok[0].keys())[:60]
            st.set(**diag)
            return jobs, len(records), diag
