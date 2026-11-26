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
            return False, "Falta BRIGHTDATA_API_KEY en .env"
        if not self.cfg["datasets"].get(source):
            return False, f"Falta el dataset_id de {source} en config.toml"
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
            raise SourceError(f"Bright Data: HTTP {resp.status_code} en {what}: {resp.text[:300]}")

    def build_input(self, source: str, keyword: str, location: str, country: str) -> dict:
        template = self.cfg.get("inputs", {}).get(source, {"keyword": "{keyword}", "location": "{location}"})
        values = {"keyword": keyword, "location": location or "", "country": country or ""}
        return {k: v.format(**values) for k, v in template.items() if v.format(**values) != ""}

    def search(self, source: str, keyword: str, location: str, country: str, run: Run) -> tuple[list[RawJob], int]:
        """Devuelve (vacantes, registros cobrados)."""
        with run.step(f"brightdata.{source}", keyword=keyword, location=location, country=country) as st:
            params = {
                "dataset_id": self.cfg["datasets"][source],
                "type": "discover_new",
                "discover_by": "keyword",
                "include_errors": "true",
                "limit_per_input": str(self.cfg["limit_per_source"]),
            }
            body = [self.build_input(source, keyword, location, country)]
            resp = self.client.post(f"{API}/trigger", params=params, json=body, headers=self._headers())
            self._check(resp, "trigger")
            snapshot_id = resp.json().get("snapshot_id")
            if not snapshot_id:
                raise SourceError(f"Bright Data: respuesta sin snapshot_id: {resp.text[:300]}")
            st.set(snapshot_id=snapshot_id)

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
            records = sr.json()
            if isinstance(records, dict):
                records = records.get("data") or records.get("records") or []
            ok = [r for r in records if isinstance(r, dict) and not r.get("error")]
            jobs = [j for j in (map_record(source, r) for r in ok) if j]
            st.set(records=len(records), errors=len(records) - len(ok), mapped=len(jobs))
            return jobs, len(records)
