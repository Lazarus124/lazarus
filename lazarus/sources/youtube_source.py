"""Búsqueda de videos para el tutor.

Con clave de YouTube Data API: búsqueda oficial con vistas, duración y fecha.
Sin clave: búsqueda web con Firecrawl limitada a youtube.com.
En los dos casos solo se devuelven videos que existen: nunca links inventados.
"""
from __future__ import annotations

import re

import httpx

from ..models import SourceError
from ..normalize import canonical_url, host_of
from ..runlog import Run

API = "https://www.googleapis.com/youtube/v3"


def _duration(iso: str | None) -> str | None:
    """PT1H2M3S -> 1:02:03"""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return f"{h}:{mi:02d}:{s:02d}" if h else f"{mi}:{s:02d}"


class YouTubeSource:
    def __init__(self, api_key: str, firecrawl=None, client: httpx.Client | None = None):
        self.api_key = api_key
        self.firecrawl = firecrawl
        self.client = client or httpx.Client(timeout=30)

    @property
    def mode(self) -> str:
        if self.api_key:
            return "api"
        if self.firecrawl and self.firecrawl.available()[0]:
            return "web"
        return "none"

    def search(self, query: str, run: Run, lang: str = "es", max_results: int = 5) -> tuple[list[dict], int]:
        """Devuelve (videos, créditos de Firecrawl usados). Cada video: title, channel, url, duration, views, published."""
        if self.mode == "api":
            return self._api(query, run, lang, max_results), 0
        if self.mode == "web":
            return self._web(query, run, max_results)
        raise SourceError("Para buscar videos conecte YouTube o Firecrawl en Configuración")

    def _api(self, query: str, run: Run, lang: str, max_results: int) -> list[dict]:
        with run.step("youtube.search", query=query) as st:
            r = self.client.get(f"{API}/search", params={
                "part": "snippet", "q": query, "type": "video", "maxResults": max_results,
                "relevanceLanguage": lang, "safeSearch": "strict", "videoEmbeddable": "true", "key": self.api_key})
            if r.status_code >= 400:
                raise SourceError(f"YouTube: HTTP {r.status_code}: {r.text[:300]}")
            items = r.json().get("items", [])
            ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
            details = {}
            if ids:
                d = self.client.get(f"{API}/videos", params={"part": "contentDetails,statistics", "id": ",".join(ids),
                                                             "key": self.api_key})
                if d.status_code < 400:
                    details = {v["id"]: v for v in d.json().get("items", [])}
            out = []
            for i in items:
                vid = i.get("id", {}).get("videoId")
                if not vid:
                    continue
                sn, det = i.get("snippet", {}), details.get(vid, {})
                out.append({"title": sn.get("title", ""), "channel": sn.get("channelTitle", ""),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "published": (sn.get("publishedAt") or "")[:10],
                            "duration": _duration(det.get("contentDetails", {}).get("duration")),
                            "views": int(det.get("statistics", {}).get("viewCount", 0) or 0)})
            st.set(results=len(out))
            return out

    def _web(self, query: str, run: Run, max_results: int) -> tuple[list[dict], int]:
        from ..usage import firecrawl_search_credits
        with run.step("youtube.web_search", query=query) as st:
            try:
                res = self.firecrawl.client.search(query, include_domains=["youtube.com"], limit=max_results * 2)
            except Exception as exc:  # noqa: BLE001
                raise SourceError(f"Firecrawl search: {exc}") from exc
            web = list(getattr(res, "web", None) or [])
            out = []
            for r in web:
                url = canonical_url(r.url)
                if host_of(url).endswith("youtube.com") and ("/watch" in url or "/playlist" in url):
                    title = getattr(r, "title", "") or ""
                    out.append({"title": re.sub(r"\s*-\s*YouTube\s*$", "", title), "channel": "", "url": url,
                                "duration": None, "views": None, "published": None})
            st.set(results=len(out))
            return out[:max_results], firecrawl_search_credits(len(web))
