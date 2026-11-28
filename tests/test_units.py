import io
import json

import httpx
import pytest

from lazarus import metrics, normalize, scoring
from lazarus.claude_client import ClaudeClient, ClaudeError
from lazarus.cv_parser import CVParseError, extract_text
from lazarus.db import DB
from lazarus.runlog import RunLogger
from lazarus.sources.brightdata_source import BrightDataSource, map_record
from tests.conftest import CV_TEXT, FakeRunner, make_docx


def test_t1_cv_parser_docx():
    text = extract_text("cv.docx", make_docx(CV_TEXT))
    assert "AWS" in text and "María" in text


def test_t1_cv_parser_pdf():
    import pdfplumber  # noqa: F401
    from docx import Document  # noqa: F401
    pdf = _minimal_pdf("Python AWS Linux soporte cloud experiencia de dos anos en empresas grandes")
    assert "Python AWS" in extract_text("cv.pdf", pdf)


def test_t1_cv_parser_rejects_empty_and_other_formats():
    with pytest.raises(CVParseError):
        extract_text("cv.docx", make_docx("hola"))
    with pytest.raises(CVParseError):
        extract_text("cv.txt", b"texto")


def test_t2_brightdata_maps_fixture_and_flow(tmp_path):
    records = json.loads(open("tests/fixtures/brightdata_linkedin_sample.json", encoding="utf-8").read())
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path.endswith("/trigger"):
            assert req.headers["authorization"] == "Bearer k"
            assert json.loads(req.content)[0]["keyword"] == "devops"
            return httpx.Response(200, json={"snapshot_id": "s_1"})
        if "/progress/" in req.url.path:
            return httpx.Response(200, json={"status": "running" if calls.count(req.url.path) < 2 else "ready"})
        return httpx.Response(200, json=records)

    cfg = {"datasets": {"linkedin": "gd_x"}, "limit_per_source": 25, "poll_interval_s": 0, "poll_timeout_s": 5,
           "inputs": {"linkedin": {"keyword": "{keyword}", "location": "{location}", "country": "{country}"}}}
    src = BrightDataSource("k", cfg, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    with log.run("search") as run:
        jobs, units, diag = src.search("linkedin", "devops", "Guadalajara", "MX", run)
    assert units == 3 and len(jobs) == 2
    assert diag["errors"] == 1 and diag["error_samples"] == ["dead_page"] and "unmapped" not in diag
    assert jobs[0].title == "DevOps Engineer Jr" and jobs[0].company == "Acme" and jobs[0].country == "MX"
    assert "<" not in jobs[0].description
    step = db.one("SELECT * FROM run_step WHERE name = 'brightdata.linkedin'")
    assert step["status"] == "ok" and json.loads(step["data_json"])["polls"] == 2


def test_t2_brightdata_missing_dataset_disabled():
    src = BrightDataSource("k", {"datasets": {"indeed": ""}})
    ok, why = src.available("indeed")
    assert not ok and "Indeed" in why
    assert map_record("linkedin", {"url": "x"}) is None


def test_t4_normalize_dedup_and_urls():
    assert normalize.canonical_url("https://WWW.x.com/a/?utm_source=z&trk=1&id=5#f") == "https://www.x.com/a?id=5"
    k1 = normalize.dedup_key("Ingeniero DevOps Jr.", "Acmé S.A.", "mx")
    k2 = normalize.dedup_key("ingeniero  devops jr", "ACME SA", "MX")
    assert k1 == k2
    assert normalize.dedup_key(None, "x", "MX") is None
    assert normalize.canon_skills(["Amazon Web Services", "AWS", "English", "K8s"]) == ["aws", "inglés", "kubernetes"]


def test_t5_scoring():
    full, _ = scoring.score(["aws", "linux", "python"], "junior", ["aws", "linux"], ["python"], "junior", "remote", "MX", "MX")
    assert full == 100
    zero, b = scoring.score([], "intern", ["aws"], ["go"], "lead", "onsite", "AR", "MX")
    assert zero == 0 and b["skills_missing_required"] == ["aws"]
    mid, b = scoring.score(["aws"], "junior", ["aws", "linux"], [], "mid", "onsite", "MX", "MX")
    assert mid == round(30 + 15 + 8 + 10)
    neutral, b = scoring.score(["aws"], "junior", [], [], "unknown", "onsite", None, "MX")
    assert b["required"] == 30 and b["seniority"] == 8 and neutral == 53


def test_t6_claude_client_retry_and_error(tmp_path):
    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    ok_after_one = FakeRunner(fail_times=1)
    c = ClaudeClient("claude", 5, 1, runner=ok_after_one)
    with log.run("cv_upload") as run:
        out = c.run("cv_profile", "<cv>x</cv>", run)
    assert out["seniority"] == "junior" and len(ok_after_one.calls) == 2
    cmd = ok_after_one.calls[0]["cmd"]
    assert "--json-schema" in cmd and "--disallowedTools" in cmd and "-p" in cmd
    assert ok_after_one.calls[0]["input"].startswith("Eres un analista de perfiles")
    steps = db.query("SELECT status FROM run_step WHERE name = 'claude.cv_profile' ORDER BY id")
    assert [s["status"] for s in steps] == ["error", "ok"]

    bad = ClaudeClient("claude", 5, 1, runner=FakeRunner(garbage=True))
    with pytest.raises(ClaudeError):
        with log.run("cv_upload") as run:
            bad.run("cv_profile", "<cv>x</cv>", run)
    assert db.one("SELECT status FROM run ORDER BY started_at DESC, rowid DESC LIMIT 1")["status"] == "error"


def test_t7_metrics_salary_insufficient():
    import pandas as pd
    df = pd.DataFrame([{"id": i, "country": "MX", "salary_min": 10000 + i, "salary_max": 20000 + i,
                        "salary_currency": "MXN", "salary_period": "month",
                        "skills_required": ["aws"], "skills_nice": []} for i in range(3)])
    out = metrics.salaries(df, 5)
    assert out.iloc[0]["mediana"] == metrics.INSUFFICIENT and out.iloc[0]["n"] == 3
    df5 = pd.concat([df] * 2, ignore_index=True).assign(id=range(6))
    assert metrics.salaries(df5, 5).iloc[0]["n"] == 6
    assert metrics.gap(df5, ["linux"]).iloc[0]["skill"] == "aws"


def test_t9_step_error_sets_statuses(tmp_path):
    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    with pytest.raises(ValueError) as ei:
        with log.run("search") as run:
            with run.step("x"):
                raise ValueError("falla")
    assert ei.value.lazarus_run_id == run.id
    assert db.one("SELECT status, duration_ms FROM run_step")["status"] == "error"
    r = db.one("SELECT status, duration_ms, error FROM run")
    assert r["status"] == "error" and r["duration_ms"] is not None and "falla" in r["error"]
    events = [json.loads(line) for line in log.events_for(run.id)]
    assert [e["event"] for e in events] == ["run_start", "step_start", "step_end", "run_end"]


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def test_claude_client_falls_back_to_result_text(tmp_path):
    """Si structured_output no viene, se lee el JSON de 'result' y se valida."""
    from types import SimpleNamespace
    from lazarus.claude_client import extract_json, validate, load_schema

    payload = {"skills": ["aws"], "seniority": "junior", "years_experience": 2, "languages": [], "roles": [],
               "summary": "x"}

    def runner(cmd, input=None, **kw):
        out = {"type": "result", "subtype": "success", "is_error": False,
               "result": "Aquí está:\n```json\n" + json.dumps(payload) + "\n```"}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")

    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    with log.run("cv_upload") as run:
        assert ClaudeClient("claude", 5, 0, runner=runner).run("cv_profile", "<cv>x</cv>", run) == payload
    step = json.loads(db.one("SELECT data_json FROM run_step")["data_json"])
    assert step["parsed_from"] == "result" and "structured_output" not in step["out_keys"]

    assert extract_json('texto {"a": 1} más') == {"a": 1}
    assert extract_json("sin json") is None
    errs = validate({"skills": "aws"}, load_schema("cv_profile"))
    assert any("falta 'seniority'" in e for e in errs) and any("$.skills" in e for e in errs)


def test_claude_auth_error_is_not_retried(tmp_path):
    from types import SimpleNamespace
    from lazarus.claude_client import ClaudeAuthError
    calls = []

    def runner(cmd, input=None, **kw):
        calls.append(1)
        out = {"type": "result", "subtype": "success", "is_error": True,
               "result": "Failed to authenticate: OAuth session expired and could not be refreshed"}
        return SimpleNamespace(returncode=1, stdout=json.dumps(out), stderr="")

    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    with pytest.raises(ClaudeAuthError) as ei:
        with log.run("cv_upload") as run:
            ClaudeClient("claude", 5, 1, runner=runner).run("cv_profile", "<cv>x</cv>", run)
    assert len(calls) == 1 and "Iniciar sesión en Claude" in str(ei.value)


def test_claude_runs_in_fixed_workdir_without_cleanup(tmp_path):
    """La carpeta de trabajo es fija: no hay borrado que falle en Windows (WinError 32)."""
    from lazarus.claude_client import workdir
    runner = FakeRunner()
    db = DB(tmp_path / "t.db")
    log = RunLogger(db, tmp_path / "logs")
    with log.run("cv_upload") as run:
        ClaudeClient("claude", 5, 0, runner=runner).run("cv_profile", "<cv>x</cv>", run)
    assert runner.calls[0]["kw"]["cwd"] == str(workdir())
    assert workdir().is_dir()


def test_indeed_input_uses_country_domain():
    from lazarus import config
    cfg = config.load()["brightdata"]
    src = BrightDataSource("k", cfg)
    assert src.build_input("indeed", "devops", "Monterrey", "mx") == {
        "country": "MX", "domain": "mx.indeed.com", "keyword_search": "devops", "location": "Monterrey"}
    assert src.build_input("indeed", "devops", "", "")["domain"] == "indeed.com"
    assert all(cfg["datasets"][s].startswith("gd_") for s in ("linkedin", "indeed", "glassdoor"))


def test_brightdata_location_required_uses_country():
    """Bright Data responde 400 'location: Required field' si va vacía: se usa el país."""
    from lazarus import config
    src = BrightDataSource("k", config.load()["brightdata"])
    for source in ("linkedin", "indeed", "glassdoor"):
        assert src.build_input(source, "arquitecto de nube", "", "AR")["location"] == "Argentina"
    assert src.build_input("linkedin", "devops", "Córdoba", "AR")["location"] == "Córdoba"
    assert src.build_input("linkedin", "devops", "", "")["location"] == "Latin America"


def test_brightdata_remote_inputs():
    from lazarus import config
    src = BrightDataSource("k", config.load()["brightdata"])
    assert src.build_input("linkedin", "devops", "", "AR", remote=True)["remote"] == "Remote"
    assert "remote" not in src.build_input("linkedin", "devops", "", "AR")
    assert src.build_input("indeed", "devops", "", "AR", remote=True)["keyword_search"] == "devops remoto"
    assert src.build_input("glassdoor", "devops", "", "US", remote=True)["keyword"] == "devops remote"


def test_long_tasks_get_longer_timeout_and_no_retry(tmp_path):
    import subprocess
    calls = []

    def runner(cmd, input=None, **kw):
        calls.append(kw["timeout"])
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    log = RunLogger(DB(tmp_path / "t.db"), tmp_path / "logs")
    c = ClaudeClient("claude", 120, 1, runner=runner, long_timeout=360)
    with pytest.raises(ClaudeError) as ei:
        with log.run("interview_prep") as run:
            c.run("interview_prep", "<cv>x</cv>", run)
    assert calls == [360] and "6 minutos" in str(ei.value) and "json-schema" not in str(ei.value)
    calls.clear()
    with pytest.raises(ClaudeError) as ei:
        with log.run("analyze") as run:
            c.run("extract_job", "<vacante>x</vacante>", run)
    assert calls == [120, 120] and "120 segundos" in str(ei.value)


def test_linkedin_experience_level_input():
    from lazarus import config
    src = BrightDataSource("k", config.load()["brightdata"])
    assert src.build_input("linkedin", "devops", "", "MX", level="junior")["experience_level"] == "Entry level"
    assert "experience_level" not in src.build_input("linkedin", "devops", "", "MX")
    assert "experience_level" not in src.build_input("indeed", "devops", "", "MX", level="junior")


def test_parse_posted_dates():
    from datetime import date
    from lazarus.normalize import parse_posted
    ref = date(2026, 11, 27)
    assert parse_posted("2026-11-20T10:00:00Z", ref) == "2026-11-20"
    assert parse_posted("hace 3 días", ref) == "2026-11-24"
    assert parse_posted("2 weeks ago", ref) == "2026-11-13"
    assert parse_posted("Publicado hace 5 horas", ref) == "2026-11-27"
    assert parse_posted("ayer", ref) == "2026-11-26"
    assert parse_posted("30+ days ago", ref) == "2026-10-28"
    assert parse_posted("hace 1 mes", ref) == "2026-10-28"
    assert parse_posted("sin fecha", ref) is None and parse_posted(None, ref) is None


def test_linkedin_time_range_input():
    from lazarus import config
    src = BrightDataSource("k", config.load()["brightdata"])
    assert src.build_input("linkedin", "devops", "", "MX", freshness="day")["time_range"] == "Past 24 hours"
    assert src.build_input("linkedin", "devops", "", "MX", freshness="3days")["time_range"] == "Past week"
    assert "time_range" not in src.build_input("linkedin", "devops", "", "MX")


def test_linkedin_modality_and_job_type_inputs():
    from lazarus import config
    src = BrightDataSource("k", config.load()["brightdata"])
    i = src.build_input("linkedin", "devops", "", "MX", modalities=["hybrid"], part_time=True)
    assert i["remote"] == "Hybrid" and i["job_type"] == "Part-time"
    assert "remote" not in src.build_input("linkedin", "devops", "", "MX", modalities=["remote", "hybrid"])
    assert src.build_input("indeed", "devops", "", "MX", modalities=["hybrid"], part_time=True)["keyword_search"] == "devops híbrido part time"
