"""Tutor Lazarus: videos reales, plan, progreso y chat."""
import httpx

from lazarus.sources.youtube_source import YouTubeSource, _duration
from tests.conftest import CV_TEXT, FakeFirecrawlClient, make_docx


def _yt_transport(calls):
    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [
                {"id": {"videoId": "abc123"}, "snippet": {"title": "Terraform desde cero", "channelTitle": "Canal Pro",
                                                          "publishedAt": "2025-03-01T10:00:00Z"}},
                {"id": {"channelId": "x"}, "snippet": {"title": "Un canal, no un video"}}]})
        return httpx.Response(200, json={"items": [
            {"id": "abc123", "contentDetails": {"duration": "PT1H5M3S"}, "statistics": {"viewCount": "12345"}}]})
    return httpx.MockTransport(handler)


def test_duration_format():
    assert _duration("PT1H5M3S") == "1:05:03"
    assert _duration("PT7M9S") == "7:09"
    assert _duration(None) is None


def test_youtube_api_mode(make_app):
    app = make_app()
    calls = []
    yt = YouTubeSource("yt-key", client=httpx.Client(transport=_yt_transport(calls)))
    assert yt.mode == "api"
    with app.log.run("test", {}) as run:
        videos, credits = yt.search("terraform", run)
    assert credits == 0
    assert videos == [{"title": "Terraform desde cero", "channel": "Canal Pro",
                       "url": "https://www.youtube.com/watch?v=abc123", "published": "2025-03-01",
                       "duration": "1:05:03", "views": 12345}]
    assert calls[0].url.params["relevanceLanguage"] == "es"


def test_youtube_web_fallback_keeps_only_real_videos(make_app):
    fc = FakeFirecrawlClient([("https://www.youtube.com/watch?v=zzz", "Curso Terraform - YouTube", ""),
                              ("https://www.youtube.com/@canal", "Canal", ""),
                              ("https://otrositio.com/watch?v=1", "Falso", "")])
    app = make_app(fc_client=fc)
    assert app.youtube.mode == "web"
    with app.log.run("test", {}) as run:
        videos, credits = app.youtube.search("terraform", run)
    assert [v["url"] for v in videos] == ["https://www.youtube.com/watch?v=zzz"]
    assert videos[0]["title"] == "Curso Terraform"
    assert fc.search_calls[0]["include_domains"] == ["youtube.com"]
    assert credits > 0


def _tutor_app(make_app, fc=None):
    app = make_app(fc_client=fc or FakeFirecrawlClient([("https://developer.hashicorp.com/terraform/tutorials", "Guía", "")]))
    app.cfg["keys"]["youtube"] = "yt-key"
    app.youtube_http = httpx.Client(transport=_yt_transport([]))
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    return app


def test_learning_plan_uses_only_found_resources(make_app):
    app = _tutor_app(make_app)
    inputs = {"skills": [{"skill": "terraform", "level": "Desde cero"}], "hours": 5, "target_date": None,
              "styles": ["Videos"], "origin": {"kind": "mercado", "label": "mercado", "job_id": None}}
    pid = app.create_learning_plan(inputs)
    lp = app.get_learning_plan(pid)
    assert lp["plan"]["total_weeks"] == 2
    # s1t1 recibe el video real; s1t2 pidió un número inventado y queda sin recurso; "otra" no es una tarea
    assert list(lp["resources"]) == ["s1t1"]
    assert lp["resources"]["s1t1"][0]["url"] == "https://www.youtube.com/watch?v=abc123"
    assert lp["resources"]["s1t1"][0]["why"] == "Claro y en español"
    # el CV va solo a Claude: nunca en las búsquedas
    assert all("María" not in c["query"] for c in app.firecrawl.client.search_calls)

    app.set_task_done(pid, "s1t1", True)
    assert app.get_learning_plan(pid)["done"] == {"s1t1"}
    app.set_task_done(pid, "s1t1", False)
    assert app.get_learning_plan(pid)["done"] == set()
    assert app.learning_plans()[0]["inputs"]["skills"][0]["skill"] == "terraform"


def test_plan_survives_without_search_sources(make_app):
    app = _tutor_app(make_app)
    app.cfg["keys"]["youtube"] = ""
    app.firecrawl.api_key = ""
    pid = app.create_learning_plan({"skills": [{"skill": "terraform", "level": "Desde cero"}], "hours": 5,
                                    "styles": [], "origin": {"kind": "mercado", "label": ""}})
    assert app.get_learning_plan(pid)["resources"] == {}


def test_tutor_chat_adds_real_videos(make_app):
    app = _tutor_app(make_app)
    pid = app.create_learning_plan({"skills": [{"skill": "terraform", "level": "Desde cero"}], "hours": 5,
                                    "styles": [], "origin": {"kind": "mercado", "label": ""}})
    out = app.tutor_chat(pid, "¿Qué sigue?")
    assert out["reply"].startswith("¡Bien!")
    assert out["videos"][0]["url"].startswith("https://www.youtube.com/watch?v=")
    msgs = app.tutor_messages(pid)
    assert [m["role"] for m in msgs] == ["user", "lazarus"]
    assert msgs[1]["videos"] == out["videos"]


def test_market_and_position_gaps(make_app, tmp_path):
    from tests.test_tracking import _app
    app, sid = _app(make_app, tmp_path)
    gaps = [g["skill"] for g in app.market_gaps()]
    assert "terraform" in gaps and "aws" not in gaps
    job_id = app.ranking(sid)[0]["job_id"]
    assert app.position_gaps(job_id) == ["terraform"]
