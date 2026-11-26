"""Casos de uso que llama la UI. Cada método público abre una corrida."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import normalize, scoring, usage
from .claude_client import ClaudeAuthError, ClaudeClient, ClaudeError
from .config import load_domains_base
from .cv_parser import extract_text
from .db import DB, now
from .letters import to_text
from .models import SourceError
from .runlog import RunLogger
from .secrets import NAMES as KEY_NAMES, SecretStore
from .sources.brightdata_source import BrightDataSource
from .sources.firecrawl_source import FirecrawlSource

BD_SOURCES = ["linkedin", "indeed", "glassdoor"]
WEB = "web"
ALL_SOURCES = BD_SOURCES + [WEB]
SOURCE_LABELS = {"linkedin": "LinkedIn Jobs", "indeed": "Indeed", "glassdoor": "Glassdoor", WEB: "Portales (Firecrawl)"}
MAX_DESC = 20_000


def run_id_of(exc: BaseException) -> str | None:
    return getattr(exc, "lazarus_run_id", None)


class Lazarus:
    def __init__(self, cfg: dict, claude=None, brightdata=None, firecrawl=None):
        self.cfg = cfg
        self.db = DB(cfg["paths"]["db"])
        self.log = RunLogger(self.db, cfg["paths"]["logs"], debug=cfg["logging"]["debug"],
                             retention_days=cfg["logging"]["retention_days"])
        self.log.cleanup()
        self.secrets = SecretStore(cfg["paths"]["data"])
        self._env_keys = dict(cfg["keys"])
        self._injected = {"brightdata": brightdata is not None, "firecrawl": firecrawl is not None}
        c = cfg["claude"]
        self.claude = claude or ClaudeClient(c["binary"], c["timeout_s"], c["retries"])
        self.brightdata = brightdata
        self.firecrawl = firecrawl
        self.apply_settings()
        self._seed_domains()

    # ------------------------------------------------------------- ajustes
    def get_setting(self, key: str) -> str | None:
        row = self.db.one("SELECT value FROM setting WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.log.run("settings", {"setting": key}):
            self.db.execute("INSERT INTO setting (key, value) VALUES (?,?)"
                            " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value.strip()))
            self.apply_settings()

    def apply_settings(self) -> None:
        """Combina config.toml, .env y lo guardado en la interfaz. La interfaz tiene prioridad."""
        for name in KEY_NAMES:
            try:
                stored = self.secrets.get(name)
            except Exception:  # noqa: BLE001 - archivo dañado o de otro usuario de Windows
                stored = ""
            self.cfg["keys"][name] = stored or self._env_keys.get(name, "")
        for s in BD_SOURCES:
            v = self.get_setting(f"dataset.{s}")
            if v is not None:
                self.cfg["brightdata"]["datasets"][s] = v
        binary = self.get_setting("claude.binary")
        if binary:
            self.cfg["claude"]["binary"] = binary
        if hasattr(self.claude, "binary"):
            self.claude.binary = self.cfg["claude"]["binary"]
        if not self._injected["brightdata"]:
            self.brightdata = BrightDataSource(self.cfg["keys"]["brightdata"], self.cfg["brightdata"])
        if not self._injected["firecrawl"]:
            self.firecrawl = FirecrawlSource(self.cfg["keys"]["firecrawl"], self.db, self.cfg["firecrawl"])

    def key_source(self, name: str) -> str | None:
        if self.secrets.has(name):
            return "interfaz"
        if self._env_keys.get(name):
            return ".env"
        return None

    def save_key(self, name: str, value: str) -> None:
        with self.log.run("settings", {"key": name}):  # nunca se registra el valor
            self.secrets.set(name, value)
            self.apply_settings()

    def delete_key(self, name: str) -> None:
        with self.log.run("settings", {"key": name, "action": "delete"}):
            self.secrets.delete(name)
            self.apply_settings()

    def test_key(self, name: str) -> dict:
        """Prueba la key sin consumir créditos. Devuelve {ok, message}."""
        import httpx

        key = self.cfg["keys"].get(name)
        if not key:
            return {"ok": False, "message": "No hay key guardada"}
        with self.log.run("key_test", {"key": name}) as run:
            with run.step(f"key_test.{name}") as st:
                try:
                    if name == "firecrawl":
                        r = httpx.get("https://api.firecrawl.dev/v2/team/credit-usage",
                                      headers={"Authorization": f"Bearer {key}"}, timeout=20)
                    else:
                        r = httpx.get("https://api.brightdata.com/zone/get_active_zones",
                                      headers={"Authorization": f"Bearer {key}"}, timeout=20)
                except httpx.HTTPError as exc:
                    st.set(result="network_error")
                    return {"ok": False, "message": f"Sin conexión: {exc}"}
                st.set(http_status=r.status_code)
                if r.status_code in (401, 403):
                    return {"ok": False, "message": "La key no es válida"}
                if r.status_code >= 400:
                    return {"ok": None, "message": f"No pude verificar la key (HTTP {r.status_code}). Pruébela con una búsqueda."}
                if name == "firecrawl":
                    data = r.json().get("data", {})
                    remaining = data.get("remainingCredits", data.get("remaining_credits"))
                    return {"ok": True, "message": f"Key válida. Créditos restantes: {remaining}"}
                return {"ok": True, "message": "Key válida"}

    # ------------------------------------------------------------------ CV
    def upload_cv(self, filename: str, data: bytes) -> dict:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        with self.log.run("cv_upload", {"ext": ext, "bytes": len(data)}) as run:
            with run.step("cv.parse") as st:
                text = extract_text(filename, data)
                st.set(chars=len(text))
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            row = self.db.one("SELECT id FROM cv WHERE sha256 = ?", (sha,))
            cv_id = row["id"] if row else self.db.execute(
                "INSERT INTO cv (filename, text, sha256, created_at) VALUES (?,?,?,?)",
                (filename, text, sha, now())).lastrowid
            self.db.execute("UPDATE cv SET active = (id = ?)", (cv_id,))
            if not self.db.one("SELECT 1 FROM cv_profile WHERE cv_id = ?", (cv_id,)):
                profile = self.claude.run("cv_profile", f"<cv>\n{text}\n</cv>", run)
                profile["skills"] = normalize.canon_skills(profile.get("skills"))
                self.db.execute(
                    "INSERT INTO cv_profile (cv_id, skills_json, seniority, profile_json) VALUES (?,?,?,?)",
                    (cv_id, json.dumps(profile["skills"], ensure_ascii=False), profile.get("seniority"),
                     json.dumps(profile, ensure_ascii=False)))
            with run.step("scoring.rescore") as st:
                st.set(matches=self._rescore(cv_id))
            return {"cv_id": cv_id, "run_id": run.id}

    def active_cv(self) -> dict | None:
        row = self.db.one(
            "SELECT c.id, c.filename, c.text, c.created_at, p.profile_json FROM cv c"
            " LEFT JOIN cv_profile p ON p.cv_id = c.id WHERE c.active = 1")
        if row:
            row["profile"] = json.loads(row.pop("profile_json") or "{}")
        return row

    def list_cvs(self) -> list[dict]:
        return self.db.query("SELECT id, filename, active, created_at FROM cv ORDER BY id DESC")

    def activate_cv(self, cv_id: int) -> None:
        with self.log.run("cv_activate", {"cv_id": cv_id}) as run:
            self.db.execute("UPDATE cv SET active = (id = ?)", (cv_id,))
            with run.step("scoring.rescore") as st:
                st.set(matches=self._rescore(cv_id))

    # ------------------------------------------------------------- dominios
    def _seed_domains(self) -> None:
        for d in load_domains_base(self.cfg["paths"]["domains_base"]):
            self.db.execute("INSERT OR IGNORE INTO domain (host, country, enabled, is_base) VALUES (?,?,1,1)",
                            (d["host"].lower(), d.get("country", "")))

    def list_domains(self) -> list[dict]:
        return self.db.query("SELECT * FROM domain ORDER BY country, host")

    def set_domain_enabled(self, domain_id: int, enabled: bool) -> None:
        self.db.execute("UPDATE domain SET enabled = ? WHERE id = ?", (int(enabled), domain_id))

    def add_domain(self, host: str, country: str = "") -> None:
        host = normalize.host_of("https://" + host.strip().removeprefix("https://").removeprefix("http://"))
        if not host or "." not in host:
            raise ValueError("Dominio inválido")
        self.db.execute("INSERT OR IGNORE INTO domain (host, country, enabled, is_base) VALUES (?,?,1,0)",
                        (host, country.upper()))

    def delete_domain(self, domain_id: int) -> None:
        self.db.execute("DELETE FROM domain WHERE id = ? AND is_base = 0", (domain_id,))

    def _hosts_for(self, country: str) -> list[str]:
        rows = self.db.query("SELECT host, country FROM domain WHERE enabled = 1")
        return [r["host"] for r in rows if not country or not r["country"] or r["country"] == country.upper()]

    # -------------------------------------------------------------- fuentes
    def source_status(self) -> dict:
        st = usage.status(self.db, self.cfg)
        out = {}
        for s in BD_SOURCES:
            ok, why = self.brightdata.available(s)
            if ok and st["brightdata"]["blocked"]:
                ok, why = False, "Plan mensual de Bright Data agotado"
            out[s] = {"ok": ok, "why": why}
        ok, why = self.firecrawl.available()
        if ok and st["firecrawl"]["blocked"]:
            ok, why = False, "Plan mensual de Firecrawl agotado"
        out[WEB] = {"ok": ok, "why": why}
        return out

    def estimate(self, sources: list[str]) -> dict:
        bd = sum(1 for s in sources if s in BD_SOURCES) * self.cfg["brightdata"]["limit_per_source"]
        fc = 0
        if WEB in sources:
            fc = usage.firecrawl_search_credits(self.cfg["firecrawl"]["search_limit"]) + self.cfg["firecrawl"]["max_scrapes"]
        return {"brightdata": bd, "firecrawl": fc}

    # ------------------------------------------------------------- búsqueda
    def search(self, keyword: str, location: str, country: str, sources: list[str], force: bool = False) -> dict:
        keyword, location, country = keyword.strip(), location.strip(), country.strip().upper()
        params = {"keyword": keyword, "location": location, "country": country, "sources": sorted(sources)}
        with self.log.run("search", params) as run:
            if not force:
                reused = self._find_recent_search(params)
                if reused:
                    run.emit("search_reused", search_id=reused["id"])
                    return {"search_id": reused["id"], "reused": True, "results": {}, "run_id": run.id}
            search_id = self.db.execute(
                "INSERT INTO search (keyword, location, country, sources_json, run_id, created_at) VALUES (?,?,?,?,?,?)",
                (keyword, location, country, json.dumps(sorted(sources)), run.id, now())).lastrowid
            status = self.source_status()
            results: dict[str, dict] = {}
            futures = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                for s in sources:
                    if not status.get(s, {}).get("ok"):
                        results[s] = {"status": "skipped", "message": status.get(s, {}).get("why", "Fuente desconocida")}
                        continue
                    if s in BD_SOURCES:
                        futures[ex.submit(self.brightdata.search, s, keyword, location, country, run)] = s
                    else:
                        hosts = self._hosts_for(country)
                        known = {r["url"] for r in self.db.query("SELECT url FROM job")}
                        futures[ex.submit(self.firecrawl.search, keyword, location, hosts, known, run)] = s
                for fut in as_completed(futures):
                    s = futures[fut]
                    service = "firecrawl" if s == WEB else "brightdata"
                    try:
                        jobs, units = fut.result()
                        usage.record(self.db, service, s, units, run.id)
                        counts = normalize.insert_raw_jobs(self.db, jobs, search_id)
                        results[s] = {"status": "ok", "found": len(jobs), "units": units, **counts}
                    except SourceError as exc:
                        results[s] = {"status": "error", "message": str(exc)}
                    except Exception as exc:  # noqa: BLE001 - una fuente no corta las demás
                        results[s] = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
                        run.emit("source_error", level="ERROR", source=s, error=str(exc)[:500])
            run.emit("search_summary", search_id=search_id, results=results)
            return {"search_id": search_id, "reused": False, "results": results, "run_id": run.id}

    def _find_recent_search(self, params: dict) -> dict | None:
        since = (datetime.now(timezone.utc) - timedelta(hours=self.cfg["search"]["reuse_hours"])).isoformat(timespec="seconds")
        return self.db.one(
            "SELECT id FROM search WHERE keyword = ? AND location = ? AND country = ? AND sources_json = ?"
            " AND created_at >= ? ORDER BY id DESC LIMIT 1",
            (params["keyword"], params["location"], params["country"], json.dumps(params["sources"]), since))

    def searches(self, limit: int = 50) -> list[dict]:
        return self.db.query(
            "SELECT s.*, COUNT(sr.job_id) AS jobs FROM search s LEFT JOIN search_result sr ON sr.search_id = s.id"
            " GROUP BY s.id ORDER BY s.id DESC LIMIT ?", (limit,))

    # -------------------------------------------------------------- análisis
    def pending_count(self, search_id: int) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM job j JOIN search_result sr ON sr.job_id = j.id"
            " WHERE sr.search_id = ? AND j.duplicate_of IS NULL AND j.analysis_status IN ('pending', 'failed')",
            (search_id,))
        return row["n"]

    def analyze(self, search_id: int, progress=None) -> dict:
        with self.log.run("analyze", {"search_id": search_id}) as run:
            jobs = self.db.query(
                "SELECT j.* FROM job j JOIN search_result sr ON sr.job_id = j.id"
                " WHERE sr.search_id = ? AND j.duplicate_of IS NULL AND j.analysis_status IN ('pending', 'failed')",
                (search_id,))
            counts = {"ok": 0, "not_job": 0, "failed": 0, "duplicates": 0}

            def work(job):
                data = (f"<vacante>\nTítulo: {job['title'] or ''}\nEmpresa: {job['company'] or ''}\n"
                        f"Ubicación: {job['location'] or ''}\nURL: {job['url']}\n\n"
                        f"{job['description'][:MAX_DESC]}\n</vacante>")
                return self.claude.run("extract_job", data, run)

            with ThreadPoolExecutor(max_workers=self.cfg["claude"]["concurrency"]) as ex:
                futs = {ex.submit(work, j): j for j in jobs}
                for i, fut in enumerate(as_completed(futs), start=1):
                    job = futs[fut]
                    try:
                        result = self._save_analysis(job, fut.result())
                        counts[result] += 1
                    except ClaudeAuthError:
                        for f in futs:
                            f.cancel()
                        raise
                    except ClaudeError:
                        self.db.execute("UPDATE job SET analysis_status = 'failed' WHERE id = ?", (job["id"],))
                        counts["failed"] += 1
                    if progress:
                        progress(i, len(jobs))
            cv = self.active_cv()
            if cv:
                with run.step("scoring.rescore") as st:
                    st.set(matches=self._rescore(cv["id"]))
            run.emit("analyze_summary", **counts)
            return {**counts, "total": len(jobs), "run_id": run.id}

    def _save_analysis(self, job: dict, a: dict) -> str:
        sal = a.get("salary") or {}
        self.db.execute(
            "INSERT OR REPLACE INTO job_analysis (job_id, is_job_posting, skills_required_json, skills_nice_json,"
            " seniority, modality, country, city, language, years_min, salary_min, salary_max, salary_currency,"
            " salary_period, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job["id"], int(bool(a.get("is_job_posting"))),
             json.dumps(normalize.canon_skills(a.get("skills_required")), ensure_ascii=False),
             json.dumps(normalize.canon_skills(a.get("skills_nice")), ensure_ascii=False),
             a.get("seniority"), a.get("modality"), (a.get("country") or "").upper() or None, a.get("city"),
             a.get("language"), a.get("years_min"), sal.get("min"), sal.get("max"), sal.get("currency"),
             sal.get("period"), now()))
        if not a.get("is_job_posting"):
            self.db.execute("UPDATE job SET analysis_status = 'not_job' WHERE id = ?", (job["id"],))
            return "not_job"
        title = job["title"] or a.get("title")
        company = job["company"] or a.get("company")
        country = job["country"] or (a.get("country") or "").upper() or None
        self.db.execute("UPDATE job SET analysis_status = 'ok', title = ?, company = ?, country = ? WHERE id = ?",
                        (title, company, country, job["id"]))
        if not job["dedup_key"] and normalize.assign_dedup(self.db, job["id"], title, company, country):
            return "duplicates"
        return "ok"

    def _rescore(self, cv_id: int) -> int:
        prof = self.db.one("SELECT skills_json, seniority FROM cv_profile WHERE cv_id = ?", (cv_id,))
        if not prof:
            return 0
        cv_skills = json.loads(prof["skills_json"])
        rows = self.db.query(
            "SELECT a.*, (SELECT s.country FROM search s JOIN search_result sr ON sr.search_id = s.id"
            "  WHERE sr.job_id = a.job_id ORDER BY s.id DESC LIMIT 1) AS search_country"
            " FROM job_analysis a JOIN job j ON j.id = a.job_id"
            " WHERE a.is_job_posting = 1 AND j.duplicate_of IS NULL")
        for r in rows:
            sc, bd = scoring.score(cv_skills, prof["seniority"], json.loads(r["skills_required_json"]),
                                   json.loads(r["skills_nice_json"]), r["seniority"], r["modality"],
                                   r["country"], r["search_country"])
            self.db.execute(
                "INSERT INTO match (cv_id, job_id, search_country, score, breakdown_json, created_at)"
                " VALUES (?,?,?,?,?,?) ON CONFLICT(cv_id, job_id) DO UPDATE SET"
                " reasons_json = CASE WHEN match.breakdown_json = excluded.breakdown_json"
                "   THEN match.reasons_json ELSE NULL END,"
                " score = excluded.score, breakdown_json = excluded.breakdown_json,"
                " search_country = excluded.search_country",
                (cv_id, r["job_id"], r["search_country"], sc, json.dumps(bd, ensure_ascii=False), now()))
        return len(rows)

    # --------------------------------------------------------------- ranking
    def ranking(self, search_id: int | None = None) -> list[dict]:
        cv = self.active_cv()
        if not cv:
            return []
        sql = ("SELECT m.id AS match_id, m.score, m.breakdown_json, m.reasons_json, j.id AS job_id, j.title,"
               " j.company, j.location, j.country, j.url, j.source, a.modality, a.seniority, a.language"
               " FROM match m JOIN job j ON j.id = m.job_id JOIN job_analysis a ON a.job_id = j.id"
               " WHERE m.cv_id = ? AND j.duplicate_of IS NULL")
        params: list = [cv["id"]]
        if search_id:
            sql += " AND j.id IN (SELECT job_id FROM search_result WHERE search_id = ?)"
            params.append(search_id)
        rows = self.db.query(sql + " ORDER BY m.score DESC, j.id DESC", params)
        for r in rows:
            r["breakdown"] = json.loads(r.pop("breakdown_json"))
            r["reasons"] = json.loads(r.pop("reasons_json")) if r["reasons_json"] else None
        return rows

    def explain(self, match_ids: list[int]) -> dict:
        cv = self.active_cv()
        with self.log.run("explain", {"matches": len(match_ids)}) as run:
            if not cv:
                raise ValueError("No hay un CV activo")
            perfil = json.dumps(cv["profile"], ensure_ascii=False)

            def work(mid):
                m = self.db.one(
                    "SELECT m.score, m.breakdown_json, j.title, j.company, a.* FROM match m"
                    " JOIN job j ON j.id = m.job_id JOIN job_analysis a ON a.job_id = j.id WHERE m.id = ?", (mid,))
                vac = {k: m[k] for k in ("title", "company", "seniority", "modality", "country", "city", "years_min")}
                vac["skills_required"] = json.loads(m["skills_required_json"])
                vac["skills_nice"] = json.loads(m["skills_nice_json"])
                data = (f"<perfil>\n{perfil}\n</perfil>\n<vacante>\n{json.dumps(vac, ensure_ascii=False)}\n</vacante>\n"
                        f"<score>\n{json.dumps({'score': m['score'], **json.loads(m['breakdown_json'])}, ensure_ascii=False)}\n</score>")
                return mid, self.claude.run("explain_match", data, run)

            done = failed = 0
            with ThreadPoolExecutor(max_workers=self.cfg["claude"]["concurrency"]) as ex:
                for fut in as_completed([ex.submit(work, mid) for mid in match_ids]):
                    try:
                        mid, res = fut.result()
                        self.db.execute("UPDATE match SET reasons_json = ? WHERE id = ?",
                                        (json.dumps(res, ensure_ascii=False), mid))
                        done += 1
                    except ClaudeAuthError:
                        raise
                    except ClaudeError:
                        failed += 1
            return {"done": done, "failed": failed, "run_id": run.id}

    def explain_top(self, search_id: int) -> dict:
        n = self.cfg["claude"]["explain_top_n"]
        ids = [r["match_id"] for r in self.ranking(search_id)[:n] if not r["reasons"]]
        return self.explain(ids) if ids else {"done": 0, "failed": 0, "run_id": None}

    # ----------------------------------------------------------------- cartas
    def generate_letter(self, match_id: int, language: str | None = None) -> dict:
        with self.log.run("cover_letter", {"match_id": match_id, "language": language}) as run:
            m = self.db.one(
                "SELECT m.cv_id, m.reasons_json, j.title, j.company, j.description, a.language AS job_language"
                " FROM match m JOIN job j ON j.id = m.job_id JOIN job_analysis a ON a.job_id = j.id WHERE m.id = ?",
                (match_id,))
            if not m:
                raise ValueError("No existe esa vacante en el ranking")
            cv = self.db.one("SELECT text FROM cv WHERE id = ?", (m["cv_id"],))
            lang = language or m["job_language"] or "es"
            reasons = json.loads(m["reasons_json"])["reasons"] if m["reasons_json"] else []
            data = (f"<cv>\n{cv['text']}\n</cv>\n<vacante>\nPuesto: {m['title'] or ''}\nEmpresa: {m['company'] or ''}\n\n"
                    f"{m['description'][:12000]}\n</vacante>\n<razones>\n{json.dumps(reasons, ensure_ascii=False)}\n</razones>\n"
                    f"<idioma>{lang}</idioma>")
            letter = self.claude.run("cover_letter", data, run)
            body = to_text(letter)
            letter_id = self.db.execute(
                "INSERT INTO cover_letter (match_id, language, body_md, created_at) VALUES (?,?,?,?)",
                (match_id, lang, body, now())).lastrowid
            return {"letter_id": letter_id, "body": body, "language": lang, "run_id": run.id}

    def save_letter(self, letter_id: int, body: str) -> None:
        self.db.execute("UPDATE cover_letter SET body_md = ? WHERE id = ?", (body, letter_id))

    def letters_for(self, match_id: int) -> list[dict]:
        return self.db.query("SELECT * FROM cover_letter WHERE match_id = ? ORDER BY id DESC", (match_id,))

    # --------------------------------------------------------------- corridas
    def runs(self, limit: int = 200, kind: str | None = None, status: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM run WHERE 1 = 1", []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if status:
            sql += " AND status = ?"
            params.append(status)
        return self.db.query(sql + " ORDER BY started_at DESC LIMIT ?", params + [limit])

    def run_steps(self, run_id: str) -> list[dict]:
        rows = self.db.query("SELECT * FROM run_step WHERE run_id = ? ORDER BY id", (run_id,))
        for r in rows:
            r["data"] = json.loads(r.pop("data_json") or "{}")
        return rows

    def performance(self, days: int = 7) -> pd.DataFrame:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        df = pd.DataFrame(self.db.query("SELECT name, status, duration_ms FROM run_step WHERE started_at >= ?", (since,)))
        if df.empty:
            return df
        g = df.groupby("name")
        return pd.DataFrame({
            "pasos": g.size(),
            "p50_ms": g["duration_ms"].quantile(0.5).round(0),
            "p95_ms": g["duration_ms"].quantile(0.95).round(0),
            "error_%": (g["status"].apply(lambda s: (s == "error").mean() * 100)).round(1),
        }).sort_values("p95_ms", ascending=False)

    def cache_stats(self, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.db.query("SELECT data_json FROM run_step WHERE name = 'firecrawl.scrape' AND started_at >= ?", (since,))
        hits = scraped = 0
        for r in rows:
            d = json.loads(r["data_json"] or "{}")
            hits += d.get("cache_hits", 0)
            scraped += d.get("scraped", 0)
        total = hits + scraped
        return {"hits": hits, "scraped": scraped, "ratio": (hits / total) if total else None}

    def export_run(self, run_id: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{run_id}.jsonl", "".join(self.log.events_for(run_id)))
            debug = self.log.log_dir / "debug" / run_id
            if debug.exists():
                for f in debug.iterdir():
                    z.write(f, f"debug/{f.name}")
        return buf.getvalue()
