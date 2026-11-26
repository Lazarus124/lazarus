"""Firecrawl: search sin scrape + scrape selectivo de URLs nuevas, con caché."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..db import DB, now
from ..models import RawJob, SourceError
from ..normalize import canonical_url, host_of
from ..runlog import Run
from ..usage import firecrawl_search_credits


class FirecrawlSource:
    def __init__(self, api_key: str, db: DB, cfg: dict, client=None):
        self.api_key = api_key
        self.db = db
        self.cfg = cfg
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from firecrawl import Firecrawl
            self._client = Firecrawl(api_key=self.api_key)
        return self._client

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Falta FIRECRAWL_API_KEY en .env"
        return True, ""

    def cache_get(self, url: str) -> str | None:
        row = self.db.one("SELECT markdown, fetched_at FROM page_cache WHERE url = ?", (url,))
        if not row:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
        return row["markdown"] if age < timedelta(days=self.cfg["cache_days"]) else None

    def cache_put(self, url: str, markdown: str) -> None:
        self.db.execute(
            "INSERT INTO page_cache (url, markdown, fetched_at) VALUES (?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET markdown = excluded.markdown, fetched_at = excluded.fetched_at",
            (url, markdown, now()),
        )

    def search(self, keyword: str, location: str, hosts: list[str], known_urls: set[str], run: Run):
        """Devuelve (jobs, créditos usados)."""
        if not hosts:
            return [], 0
        query = f"{keyword} {location}".strip()
        with run.step("firecrawl.search", query=query, hosts=len(hosts)) as st:
            try:
                res = self.client.search(query, include_domains=hosts, limit=self.cfg["search_limit"])
            except Exception as exc:  # noqa: BLE001 - el SDK lanza varios tipos
                raise SourceError(f"Firecrawl search: {exc}") from exc
            web = list(getattr(res, "web", None) or [])
            credits = firecrawl_search_credits(len(web))
            allowed = set(hosts)
            hits = []
            for r in web:
                url = canonical_url(r.url)
                if any(host_of(url) == h or host_of(url).endswith("." + h) for h in allowed):
                    hits.append((url, getattr(r, "title", None)))
            st.set(results=len(web), in_domains=len(hits), credits=credits)

        new = [(u, t) for u, t in hits if u not in known_urls]
        jobs: list[RawJob] = []
        with run.step("firecrawl.scrape", candidates=len(new)) as st:
            cached = scraped = failed = 0
            for url, title in new[: self.cfg["max_scrapes"]]:
                md = self.cache_get(url)
                if md is None:
                    try:
                        doc = self.client.scrape(url, formats=["markdown"], only_main_content=True)
                        md = getattr(doc, "markdown", None) or ""
                        scraped += 1
                    except Exception:  # noqa: BLE001 - una página fallida no corta la búsqueda
                        failed += 1
                        continue
                    if md:
                        self.cache_put(url, md)
                else:
                    cached += 1
                if md:
                    jobs.append(RawJob(source=f"web:{host_of(url)}", url=url, title=title, description=md))
            st.set(scraped=scraped, cache_hits=cached, failed=failed, credits=scraped)
        return jobs, credits + scraped
