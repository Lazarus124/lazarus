"""Posiciones cerradas, seguimiento y copia del CV al postularse."""
from pathlib import Path

from lazarus.models import RawJob
from tests.conftest import CV_TEXT, FakeBrightData, FakeFirecrawlClient, make_docx


def _app(make_app, tmp_path, fc=None):
    jobs = {"linkedin": [
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/41", "DevOps. AWS.", title="DevOps: Jr/Cloud", company="Acme S.A.", country="MX"),
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/42", "No longer accepting applications. AWS.", title="Cerrada 1", company="B", country="MX"),
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/43", "CERRADA_MARCA. AWS.", title="Cerrada 2", company="C", country="MX"),
        RawJob("linkedin", "https://www.linkedin.com/jobs/view/44", "Soporte. AWS.", title="Otra", company="D", country="MX"),
    ]}
    app = make_app(brightdata=FakeBrightData(jobs), fc_client=fc)
    app.set_setting("applications_dir", str(tmp_path / "aplicaciones"))
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "", "MX", ["linkedin"])["search_id"]
    app.analyze(sid)
    return app, sid


def test_closed_positions_are_hidden(make_app, tmp_path):
    app, sid = _app(make_app, tmp_path)
    assert {r["title"] for r in app.ranking(sid)} == {"DevOps: Jr/Cloud", "Otra"}
    assert len(app.ranking(sid, include_closed=True)) == 4


def test_tracking_statuses_and_hidden(make_app, tmp_path):
    app, sid = _app(make_app, tmp_path)
    ids = {r["title"]: r["job_id"] for r in app.ranking(sid)}
    app.set_status(ids["Otra"], "no_mostrar")
    assert {r["title"] for r in app.ranking(sid)} == {"DevOps: Jr/Cloud"}
    assert any(r["tracking"] == "no_mostrar" for r in app.ranking(sid, include_hidden=True))
    app.set_status(ids["DevOps: Jr/Cloud"], "favorito")
    assert app.positions_for_interview(only_tracked=True)[0]["job_id"] == ids["DevOps: Jr/Cloud"]
    app.set_status(ids["DevOps: Jr/Cloud"], None)
    assert app.tracked(["favorito"]) == []


def test_applied_saves_cv_copy_with_company_and_position(make_app, tmp_path):
    app, sid = _app(make_app, tmp_path)
    jid = next(r["job_id"] for r in app.ranking(sid) if r["company"] == "Acme S.A.")
    res = app.set_status(jid, "aplicado")
    files = [Path(f) for f in res["files"]]
    assert files[0].name == "CV - Acme S.A. - DevOps Jr Cloud.docx"  # sin caracteres no válidos en Windows
    assert files[0].read_bytes()[:2] == b"PK" and files[0].parent == tmp_path / "aplicaciones"
    # Con CV a medida y carta, se guardan las dos
    app.tailor_cv(jid)
    app.generate_letter(next(r["match_id"] for r in app.ranking(sid) if r["job_id"] == jid))
    app.set_status(jid, None)
    res = app.set_status(jid, "aplicado")
    names = sorted(Path(f).name for f in res["files"])
    assert names == ["CV - Acme S.A. - DevOps Jr Cloud (2).docx", "Carta - Acme S.A. - DevOps Jr Cloud.docx"]
    t = app.tracked(["aplicado"])[0]
    assert t["applied_at"] and len(t["files"]) == 2


def test_verify_open_marks_closed(make_app, tmp_path):
    fc = FakeFirecrawlClient([("https://occ.com.mx/empleo/9", "DevOps", "DevOps en Beta. AWS.")])
    app, sid = _app(make_app, tmp_path, fc)
    jid = app.add_job_from_url("https://occ.com.mx/empleo/9")
    fc.results = [("https://occ.com.mx/empleo/9", "DevOps", "Esta oferta ya no está disponible")]
    res = app.verify_open(jid)
    assert res["closed"] and app.db.one("SELECT closed FROM job WHERE id = ?", (jid,))["closed"] == 1
