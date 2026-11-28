"""Investigación de empresa, CV a medida, posición desde un link y preparación de entrevista."""
import io

from docx import Document

from lazarus.documents import cv_to_docx, prep_to_docx
from tests.conftest import CV_TEXT, FakeBrightData, FakeFirecrawlClient, make_docx
from tests.test_flow import _bd_jobs


def _ready(make_app, fc_results=None):
    fc = FakeFirecrawlClient(fc_results or [("https://acme.com/about", "Acme", "Acme hace software cloud.")])
    bd = FakeBrightData(_bd_jobs())
    app = make_app(brightdata=bd, fc_client=fc)
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "Guadalajara", "MX", ["linkedin"])["search_id"]
    app.analyze(sid)
    return app, fc, bd, app.ranking(sid)


def test_research_company_uses_only_real_sources(make_app):
    app, fc, _, ranking = _ready(make_app)
    job = next(r for r in ranking if r["company"] == "Acme")
    res = app.research_company(job["job_id"])
    assert any("Acme" in c["query"] for c in fc.search_calls)
    assert all(c["include_domains"] is None for c in fc.search_calls)  # búsqueda abierta
    assert [s["url"] for s in res["sources"]] == ["https://acme.com/about"]  # descarta la URL inventada
    assert app.get_company_research("ACME S.A.")["summary"].startswith("Acme")
    blob = str(app.db.query("SELECT * FROM run_step")) + str(app.db.query("SELECT * FROM run"))
    assert "SECRETO_CV_MARCADOR" not in blob


def test_tailor_cv_and_docx(make_app):
    app, _, _, ranking = _ready(make_app)
    jid = ranking[0]["job_id"]
    cv = app.tailor_cv(jid)
    assert app.get_tailored_cv(jid)["headline"] == cv["headline"]
    text = "\n".join(p.text for p in Document(io.BytesIO(cv_to_docx(cv))).paragraphs)
    assert "María Ejemplo López" in text and "Resolví incidentes en AWS." in text


def test_add_job_from_url_web_and_linkedin(make_app):
    app, fc, bd, _ = _ready(make_app, [("https://occ.com.mx/empleo/123", "DevOps", "DevOps en Beta. AWS, Linux.")])
    jid = app.add_job_from_url("occ.com.mx/empleo/123")
    assert app.job_detail(jid)["url"] == "https://occ.com.mx/empleo/123"
    assert any(p["job_id"] == jid for p in app.positions_for_interview())
    lid = app.add_job_from_url("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4242")
    assert ("url", "linkedin", "https://www.linkedin.com/jobs/view/4242") in bd.calls
    assert app.job_detail(lid)["company"] == "Acme"
    assert app.add_job_from_url("https://occ.com.mx/empleo/123") == jid  # no repite


def test_interview_process_stages_notes_and_deep_prep(make_app):
    app, _, _, ranking = _ready(make_app)
    jid = ranking[0]["job_id"]
    prep = app.interview_prep(jid)
    stages = app.interview_stages(jid)
    assert [s["name"] for s in stages] == ["Reclutador/a", "Hiring manager", "Técnica"]
    assert all(s["status"] == "pendiente" for s in stages)
    # Ya tuvo la del reclutador/a; anota cómo le fue y prepara la técnica a fondo
    app.save_stage(jid, "Reclutador/a", "hecha", "Bien, pero me fue mal en redes")
    deep = app.prepare_stage(jid, "Técnica")
    assert "usa notas previas" in deep["focus"]
    stages = app.interview_stages(jid)
    assert stages[0]["status"] == "hecha" and stages[2]["deep"]["questions"][0]["follow_up"]
    # Etapa agregada por el usuario
    app.add_stage(jid, "Entrevista con el CTO")
    assert app.interview_stages(jid)[-1]["name"] == "Entrevista con el CTO"
    # Volver a generar el plan no borra notas
    app.interview_prep(jid)
    assert app.interview_stages(jid)[0]["notes"].startswith("Bien")
    fb = app.interview_feedback(jid, "¿Qué es una VPC?", "Una red privada.", "Hiring manager")
    assert fb["score"] == 3
    text = "\n".join(p.text for p in Document(io.BytesIO(prep_to_docx(prep, "DevOps · Acme", stages))).paragraphs)
    assert "etapa 3: técnica" in text.lower() and "¿Cómo depura una VPC?" in text and "Terraform" in text


def test_worker_call_task(make_app):
    from lazarus.worker import Worker
    app, _, _, ranking = _ready(make_app)
    w = Worker(app)
    jid = ranking[0]["job_id"]
    tid = w.submit_call("Diseñando CV", f"cv:{jid}", app.tailor_cv, jid)
    w.wait()
    t = w.latest_for_key(f"cv:{jid}")
    assert t.status == "done" and t.result["name"] == "María Ejemplo López"


def test_user_picks_stages_and_what_to_prepare(make_app):
    app, _, _, ranking = _ready(make_app)
    jid = ranking[0]["job_id"]
    # Elige etapas: quedan en el orden típico y la propia al final; nada se genera todavía
    app.set_stages(jid, ["Entrevista técnica", "Con el cliente", "Reclutador/a"])
    stages = app.interview_stages(jid)
    assert [s["name"] for s in stages] == ["Reclutador/a", "Entrevista técnica", "Con el cliente"]
    assert stages[0]["plan"]["interviewer"].startswith("Reclutador")  # descripción del catálogo
    assert stages[2]["plan"] is None and all(s["deep"] is None for s in stages)
    calls = len(app._runner.calls)
    # Prepara solo la técnica
    app.prepare_stage(jid, "Entrevista técnica")
    assert len(app._runner.calls) == calls + 1
    assert [bool(s["deep"]) for s in app.interview_stages(jid)] == [False, True, False]
    # Quitar etapas: la vacía se borra, la preparada se conserva
    kept = app.set_stages(jid, ["Reclutador/a"])
    assert kept == ["Entrevista técnica"]
    assert [s["name"] for s in app.interview_stages(jid)] == ["Reclutador/a", "Entrevista técnica"]
    stages = app.interview_stages(jid)
    text = "\n".join(p.text for p in Document(io.BytesIO(prep_to_docx(None, "DevOps · Acme", stages))).paragraphs)
    assert "ETAPA 1: RECLUTADOR/A" in text and "Todavía sin preparar." in text and "¿Cómo depura una VPC?" in text
