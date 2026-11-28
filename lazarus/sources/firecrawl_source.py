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
            return False, "Falta la clave de Firecrawl (en Configuración)"
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

    def search(self, keyword: str, location: str, hosts: list[str], known_urls: set[str], run: Run,
               max_pages: int | None = None):
        """Devuelve (jobs, créditos usados)."""
        if not hosts:
            return [], 0
        query = f"{keyword} {location}".strip()
        max_pages = max_pages or self.cfg["max_scrapes"]
        limit = min(100, max(self.cfg["search_limit"], max_pages * 2))  # más resultados para elegir páginas nuevas
        with run.step("firecrawl.search", query=query, hosts=len(hosts)) as st:
            try:
                res = self.client.search(query, include_domains=hosts, limit=limit)
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
            for url, title in new[:max_pages]:
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

    # ------------------------------------------------------------- otros usos
    def find(self, query: str, run: Run, limit: int = 5) -> tuple[list[dict], int]:
        """Una búsqueda web sin leer las páginas (cursos y documentación del tutor). Devuelve (resultados, créditos)."""
        with run.step("firecrawl.find", query=query) as st:
            try:
                res = self.client.search(query, limit=limit)
            except Exception as exc:  # noqa: BLE001
                raise SourceError(f"Firecrawl search: {exc}") from exc
            web = list(getattr(res, "web", None) or [])
            out = [{"title": getattr(r, "title", "") or "", "url": canonical_url(r.url),
                    "text": (getattr(r, "description", "") or "")[:400]} for r in web if getattr(r, "url", None)]
            st.set(results=len(out))
            return out, firecrawl_search_credits(len(web))

    def research(self, queries: list[str], run: Run, max_pages: int = 3, per_query: int = 5) -> tuple[list[dict], int]:
        """Búsqueda web abierta (sin lista de dominios) para investigar una empresa.
        Devuelve (fuentes, créditos). Cada fuente: title, url, text."""
        sources: dict[str, dict] = {}
        credits = 0
        with run.step("firecrawl.research", queries=len(queries)) as st:
            for q in queries:
                try:
                    res = self.client.search(q, limit=per_query)
                except Exception as exc:  # noqa: BLE001
                    raise SourceError(f"Firecrawl search: {exc}") from exc
                web = list(getattr(res, "web", None) or [])
                credits += firecrawl_search_credits(len(web))
                for r in web:
                    url = canonical_url(r.url)
                    if url not in sources:
                        sources[url] = {"title": getattr(r, "title", "") or "", "url": url,
                                        "text": getattr(r, "description", "") or ""}
            scraped = 0
            for src in list(sources.values())[:max_pages]:
                md = self.cache_get(src["url"])
                if md is None:
                    try:
                        md = getattr(self.client.scrape(src["url"], formats=["markdown"], only_main_content=True),
                                     "markdown", "") or ""
                        scraped += 1
                        if md:
                            self.cache_put(src["url"], md)
                    except Exception:  # noqa: BLE001 - una página fallida no corta la investigación
                        continue
                src["text"] = (md or src["text"])[:6000]
            credits += scraped
            st.set(sources=len(sources), scraped=scraped, credits=credits)
        return list(sources.values()), credits

    def scrape_one(self, url: str, run: Run) -> tuple[str, int]:
        """Lee una página (para una posición que trae el usuario). Devuelve (markdown, créditos)."""
        with run.step("firecrawl.scrape_one") as st:
            md = self.cache_get(url)
            if md is not None:
                st.set(cache_hit=True)
                return md, 0
            try:
                doc = self.client.scrape(url, formats=["markdown"], only_main_content=True)
            except Exception as exc:  # noqa: BLE001
                raise SourceError(f"No pude leer la página: {exc}") from exc
            md = getattr(doc, "markdown", "") or ""
            if md:
                self.cache_put(url, md)
            st.set(chars=len(md))
            return md, 1

    def fetch_fresh(self, url: str, run: Run) -> tuple[str | None, int | None]:
        """Lee la página sin usar la caché (para verificar si la posición sigue abierta).
        Devuelve (markdown, código HTTP). markdown es None si la página no se pudo leer."""
        with run.step("firecrawl.verify") as st:
            try:
                doc = self.client.scrape(url, formats=["markdown"], only_main_content=True, max_age=0)
            except Exception as exc:  # noqa: BLE001 - una página que ya no existe suele dar error
                st.set(error=str(exc)[:200])
                return None, None
            meta = getattr(doc, "metadata", None)
            status = getattr(meta, "status_code", None) or getattr(meta, "statusCode", None)
            if status is None and isinstance(meta, dict):
                status = meta.get("statusCode") or meta.get("status_code")
            md = getattr(doc, "markdown", "") or ""
            if md and (status is None or status < 400):
                self.cache_put(url, md)
            st.set(http_status=status, chars=len(md))
            return md, status
