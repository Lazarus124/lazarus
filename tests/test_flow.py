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
