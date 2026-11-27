"""Recorrido completo con fakes: CV -> búsqueda -> análisis -> ranking -> carta -> métricas -> logs."""
import json
import zipfile
import io

from lazarus import metrics
from lazarus.letters import to_docx_bytes
from lazarus.models import RawJob
from tests.conftest import CV_TEXT, FakeBrightData, FakeFirecrawlClient, FakeRunner, make_docx


def _bd_jobs():
    return {"linkedin": [
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/1?trk=x", "Buscamos DevOps. AWS, Linux, Terraform.",
               title="DevOps Jr", company="Acme", location="Guadalajara", country="MX"),
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/2", "Cloud support Remoto. AWS.",
               title="Cloud Support", company="Beta", location="Remoto", country="MX"),
    ]}


def _fc():
    return FakeFirecrawlClient([
        ("https://mx.computrabajo.com/oferta-1", "DevOps Jr - Acme", "DevOps Jr en Acme. AWS, Linux."),
        ("https://occ.com.mx/empleo/2", "Listado", "No es vacante: listado de 50 empleos"),
        ("https://otro-sitio.com/x", "Fuera de lista", "irrelevante"),
    ])


def test_full_flow(make_app):
    fc = _fc()
    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=fc)

    cv = app.upload_cv("cv.docx", make_docx(CV_TEXT))
    prof = app.active_cv()["profile"]
    assert "aws" in prof["skills"] and "inglés" in prof["skills"]

    res = app.search("devops", "Guadalajara", "MX", ["linkedin", "web"])
    assert res["results"]["linkedin"]["status"] == "ok"
    assert res["results"]["web"]["status"] == "ok"
    assert fc.search_calls[0]["include_domains"] and "mx.computrabajo.com" in fc.search_calls[0]["include_domains"]
    assert "otro-sitio.com/x" not in " ".join(fc.scrape_calls)

    sid = res["search_id"]
    a = app.analyze(sid)
    assert a["not_job"] == 1 and a["failed"] == 0
    # El dedup ocurre: la vacante de Computrabajo con la misma empresa y título que LinkedIn queda duplicada
    # solo si coinciden título y empresa; aquí el título viene del scrape ("DevOps Jr - Acme"), así que no coincide.
    ranking = app.ranking(sid)
    assert len(ranking) >= 2
    assert ranking == sorted(ranking, key=lambda r: -r["score"])
    top = ranking[0]
    assert top["breakdown"]["skills_matched"]

    e = app.explain_top(sid)
    assert e["done"] >= 1
    assert app.ranking(sid)[0]["reasons"]["reasons"]

    letter = app.generate_letter(top["match_id"])
    assert "Acme" in letter["body"] or letter["body"].startswith("Estimado")
    assert to_docx_bytes(letter["body"])[:2] == b"PK"

    df = metrics.load_frame(app.db, search_id=sid)
    assert len(df) == len(ranking)
    assert not metrics.top_skills(df).empty

    # Búsqueda igual reciente: se reutiliza
    again = app.search("devops", "Guadalajara", "MX", ["linkedin", "web"])
    assert again["reused"] and again["search_id"] == sid

    # Segunda búsqueda forzada: Firecrawl no vuelve a hacer scrape de URLs ya guardadas
    before = len(fc.scrape_calls)
    app.search("devops", "Guadalajara", "MX", ["web"], force=True)
    assert len(fc.scrape_calls) == before

    # Exportar una corrida
    z = zipfile.ZipFile(io.BytesIO(app.export_run(res["run_id"])))
    assert any(n.endswith(".jsonl") for n in z.namelist())
    assert not app.performance(7).empty


def test_t8_logs_have_no_cv_text_or_keys(make_app, cfg):
    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=_fc())
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "", "MX", ["linkedin", "web"])["search_id"]
    app.analyze(sid)
    app.generate_letter(app.ranking(sid)[0]["match_id"])
    blob = "".join(p.read_text(encoding="utf-8") for p in cfg["paths"]["logs"].glob("*.jsonl"))
    blob += json.dumps(app.db.query("SELECT * FROM run_step")) + json.dumps(app.db.query("SELECT * FROM run"))
    assert "SECRETO_CV_MARCADOR" not in blob
    assert "fc-test" not in blob and "bd-test" not in blob
    assert not (cfg["paths"]["logs"] / "debug").exists()


def test_tr3_sources_never_receive_cv_text(make_app):
    bd = FakeBrightData(_bd_jobs())
    fc = _fc()
    app = make_app(brightdata=bd, fc_client=fc)
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    app.search("devops", "Guadalajara", "MX", ["linkedin", "web"])
    sent = json.dumps(bd.calls) + json.dumps(fc.search_calls) + json.dumps(fc.scrape_calls)
    assert "SECRETO_CV_MARCADOR" not in sent and "María" not in sent


def test_source_failure_does_not_stop_others(make_app):
    app = make_app(brightdata=FakeBrightData(_bd_jobs(), fail={"indeed"}), fc_client=_fc())
    res = app.search("devops", "", "MX", ["linkedin", "indeed"])
    assert res["results"]["indeed"]["status"] == "error"
    assert res["results"]["linkedin"]["status"] == "ok"
    step = app.db.one("SELECT status FROM run_step WHERE name = 'brightdata.indeed'")
    assert step["status"] == "error"


def test_debug_mode_writes_debug_folder(make_app, cfg):
    app = make_app()
    app.log.debug = True
    res = app.upload_cv("cv.docx", make_docx(CV_TEXT))
    folder = cfg["paths"]["logs"] / "debug" / res["run_id"]
    assert folder.exists() and any("stdin" in f.name for f in folder.iterdir())


def test_claude_failure_marks_job_failed(make_app):
    app = make_app(brightdata=FakeBrightData(_bd_jobs()))
    sid = app.search("devops", "", "MX", ["linkedin"])["search_id"]
    app.claude.runner = FakeRunner(garbage=True)
    a = app.analyze(sid)
    assert a["failed"] == 2
    assert app.pending_count(sid) == 2


def test_country_filter_and_country_in_portal_query(make_app):
    """Búsqueda en AR: las ofertas de Chile se ocultan por defecto y el país va en la consulta a los portales."""
    fc = FakeFirecrawlClient([("https://getonbrd.com/jobs/arq-cl", "Arquitecto Cloud - Chile", "Arquitecto cloud en Chile. AWS.")])
    bd = FakeBrightData({"linkedin": [RawJob("linkedin", "https://www.linkedin.com/jobs/view/9", "Arquitecto AWS.",
                                             title="Arquitecto", company="Acme", country="AR")]})
    app = make_app(brightdata=bd, fc_client=fc)
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("arquitecto de nube", "", "AR", ["linkedin", "web"])["search_id"]
    assert "Argentina" in fc.search_calls[0]["query"]
    app.analyze(sid)
    # El fake de Claude devuelve country="MX" para todas: se fuerza Chile en la de Get on Board
    app.db.execute("UPDATE job_analysis SET country = 'CL' WHERE job_id = (SELECT id FROM job WHERE url LIKE '%getonbrd%')")
    app.db.execute("UPDATE job_analysis SET country = 'AR' WHERE job_id = (SELECT id FROM job WHERE url LIKE '%linkedin%')")
    shown = {r["url"] for r in app.ranking(sid, other_countries=False)}
    assert shown == {"https://www.linkedin.com/jobs/view/9"}
    assert len(app.ranking(sid, other_countries=True)) == 2


def test_brightdata_unmapped_records_report_keys(tmp_path):
    import httpx
    from lazarus.db import DB
    from lazarus.runlog import RunLogger
    from lazarus.sources.brightdata_source import BrightDataSource

    def handler(req):
        if req.url.path.endswith("/trigger"):
            return httpx.Response(200, json={"snapshot_id": "s"})
        if "/progress/" in req.url.path:
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(200, json=[{"link": "x", "texto_raro": "y"}])

    cfg = {"datasets": {"indeed": "gd_x"}, "limit_per_source": 5, "poll_interval_s": 0, "poll_timeout_s": 5, "inputs": {}}
    src = BrightDataSource("k", cfg, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    log = RunLogger(DB(tmp_path / "t.db"), tmp_path / "logs")
    with log.run("search") as run:
        jobs, units, diag = src.search("indeed", "devops", "", "MX", run)
    assert jobs == [] and diag["unmapped"] == 1 and diag["sample_keys"] == ["link", "texto_raro"]


def test_all_portals_and_max_pages(make_app):
    fc = FakeFirecrawlClient([(f"https://bumeran.com.ar/oferta-{i}", f"Oferta {i}", f"Oferta {i}. AWS.") for i in range(10)])
    app = make_app(fc_client=fc)
    app.search("devops", "", "MX", ["web"], all_portals=True, max_pages=3)
    assert "bumeran.com.ar" in fc.search_calls[0]["include_domains"]  # portal de AR aunque el país es MX
    assert len(fc.scrape_calls) == 3
    assert app.estimate(["web"], 30)["firecrawl"] == 12 + 30  # 60 resultados = 12 créditos + 30 páginas


def test_export_search_report(make_app):
    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=_fc())
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "", "AR", ["linkedin", "web"])["search_id"]
    app.analyze(sid)
    app.explain_top(sid)
    z = zipfile.ZipFile(io.BytesIO(app.export_search(sid)))
    assert {"LEEME.txt", "resumen.json", "eventos.jsonl"} <= set(z.namelist())
    summary = json.loads(z.read("resumen.json"))
    assert {r["kind"] for r in summary["runs"]} == {"search", "analyze", "explain"}
    fc_step = next(s for r in summary["runs"] for s in r["steps"] if s["name"] == "firecrawl.search")
    assert fc_step["data"]["query"] == "devops Argentina"
    assert summary["jobs_by_source"]["linkedin"] == 2
    blob = b"".join(z.read(n) for n in z.namelist())
    assert b"SECRETO_CV_MARCADOR" not in blob


def test_remote_search(make_app):
    fc = _fc()
    bd = FakeBrightData(_bd_jobs())
    app = make_app(brightdata=bd, fc_client=fc)
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "", "MX", ["linkedin", "web"], remote=True)["search_id"]
    assert fc.search_calls[0]["query"] == "devops remoto México"
    assert app.db.one("SELECT remote FROM search WHERE id = ?", (sid,))["remote"] == 1
    app.analyze(sid)
    # El fake de Claude marca "remote" solo la vacante con "Remoto" en el texto (Cloud Support)
    titles = {r["title"] for r in app.ranking(sid)}
    assert titles == {"Cloud Support"}
    assert len(app.ranking(sid, remote_only=False)) > 1
    # Una búsqueda igual pero no remota no reutiliza la remota
    assert not app.search("devops", "", "MX", ["linkedin", "web"])["reused"]


def test_old_database_gets_remote_column(tmp_path):
    import sqlite3
    from lazarus.db import DB
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE search (id INTEGER PRIMARY KEY, keyword TEXT NOT NULL, location TEXT, country TEXT,"
                " sources_json TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO search (keyword, sources_json, created_at) VALUES ('x', '[]', 'now')")
    con.commit()
    con.close()
    db = DB(path)
    assert db.one("SELECT remote FROM search")["remote"] == 0
