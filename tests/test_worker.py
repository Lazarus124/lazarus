"""Trabajo en segundo plano: la búsqueda y la revisión siguen sin la interfaz."""
from lazarus.worker import Worker
from tests.conftest import CV_TEXT, FakeBrightData, FakeRunner, make_docx
from tests.test_flow import _bd_jobs, _fc


def test_search_pipeline_runs_in_background(make_app):
    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=_fc())
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    w = Worker(app)
    tid = w.submit_search(keyword="devops", location="", country="MX", sources=["linkedin", "web"])
    w.wait()
    t = w.get(tid)
    assert t.status == "done", t.error
    assert t.search_id and t.results["linkedin"]["status"] == "ok"
    assert t.summary["analysis"]["ok"] >= 2 and t.done == t.total
    assert app.pending_count(t.search_id) == 0
    assert app.ranking(t.search_id)[0]["reasons"]


def test_resume_pending_and_no_duplicate_tasks(make_app):
    app = make_app(brightdata=FakeBrightData(_bd_jobs()))
    sid = app.search("devops", "", "MX", ["linkedin"])["search_id"]
    assert app.pending_count(sid) == 2
    w = Worker(app)
    w.q.put = lambda task: None  # no ejecutar: solo verificar la cola
    assert w.resume_pending() == 1
    first = w.for_search(sid).id
    assert w.submit_analysis(sid) == first  # no duplica


def test_auth_error_is_reported(make_app):
    from types import SimpleNamespace
    import json
    app = make_app(brightdata=FakeBrightData(_bd_jobs()))
    sid = app.search("devops", "", "MX", ["linkedin"])["search_id"]

    def runner(cmd, input=None, **kw):
        out = {"is_error": True, "subtype": "success", "result": "Failed to authenticate: OAuth session expired"}
        return SimpleNamespace(returncode=1, stdout=json.dumps(out), stderr="")

    app.claude.runner = runner
    w = Worker(app)
    tid = w.submit_analysis(sid)
    w.wait()
    t = w.get(tid)
    assert t.status == "error" and t.auth_error and t.run_id
