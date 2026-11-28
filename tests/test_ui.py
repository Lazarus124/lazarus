"""Humo de la UI: cada página carga sin excepciones (sin red y sin claude)."""
import pytest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

# pages/0_Inicio.py se prueba a través de app.py (usa enlaces del menú de navegación).
PAGES = ["app.py", "pages/1_CV.py", "pages/2_Buscar.py", "pages/3_Vacantes.py", "pages/4_Carta.py",
         "pages/5_Mercado.py", "pages/6_Configuracion.py", "pages/7_Corridas.py",
         "pages/8_Entrevista.py", "pages/9_Seguimiento.py", "pages/10_Tutor.py"]


@pytest.mark.parametrize("path", PAGES)
def test_page_loads(path, tmp_path, monkeypatch):
    monkeypatch.setenv("LAZARUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "")  # sin claude: la página de inicio muestra el error, no falla
    from lazarus.ui import get_app
    get_app.clear()
    at = AppTest.from_file(str(ROOT / path), default_timeout=30)
    at.run()
    assert not at.exception, at.exception


def _clear_cache():
    from lazarus.ui import get_app
    get_app.clear()


@pytest.mark.parametrize("path", PAGES)
def test_page_loads_with_data(path, make_app, cfg, monkeypatch):
    from tests.conftest import CV_TEXT, make_docx
    from tests.test_flow import _bd_jobs, _fc
    from tests.conftest import FakeBrightData

    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=_fc())
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "Guadalajara", "MX", ["linkedin", "web"])["search_id"]
    app.analyze(sid)
    app.explain_top(sid)
    app.generate_letter(app.ranking(sid)[0]["match_id"])
    app.db.close()

    monkeypatch.setenv("LAZARUS_DATA_DIR", str(cfg["paths"]["data"]))
    monkeypatch.setenv("PATH", "")
    _clear_cache()
    at = AppTest.from_file(str(ROOT / path), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    _clear_cache()


def test_sidebar_shows_login_when_session_expired(tmp_path, monkeypatch):
    """Con la sesión vencida, la barra lateral ofrece «Iniciar sesión en Claude»."""
    from lazarus import claude_client as cc
    monkeypatch.setenv("LAZARUS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cc, "resolve_binary", lambda b="claude": "/bin/claude")
    monkeypatch.setattr(cc, "auth_status", lambda b="claude", runner=None: {
        "supported": True, "logged_in": False, "email": None, "detail": ""})
    import lazarus.ui as ui
    monkeypatch.setattr(ui, "resolve_binary", cc.resolve_binary)
    monkeypatch.setattr(ui, "auth_status", cc.auth_status)
    ui.get_app.clear()
    at = AppTest.from_file(str(ROOT / "pages/1_CV.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert any(b.label == "Iniciar sesión en Claude" for b in at.sidebar.button)
    ui.get_app.clear()


def test_interview_page_with_stages(make_app, cfg, monkeypatch):
    from tests.conftest import CV_TEXT, FakeBrightData, make_docx
    from tests.test_flow import _bd_jobs, _fc
    app = make_app(brightdata=FakeBrightData(_bd_jobs()), fc_client=_fc())
    app.upload_cv("cv.docx", make_docx(CV_TEXT))
    sid = app.search("devops", "Guadalajara", "MX", ["linkedin"])["search_id"]
    app.analyze(sid)
    jid = app.ranking(sid)[0]["job_id"]
    app.set_stages(jid, ["Reclutador/a", "Hiring manager", "Mi etapa"])
    app.save_stage(jid, "Reclutador/a", "hecha", "Todo bien")
    app.prepare_stage(jid, "Hiring manager")
    app.tailor_cv(jid)
    app.db.close()
    monkeypatch.setenv("LAZARUS_DATA_DIR", str(cfg["paths"]["data"]))
    monkeypatch.setenv("PATH", "")
    _clear_cache()
    for path in ("pages/8_Entrevista.py", "pages/3_Vacantes.py"):
        at = AppTest.from_file(str(ROOT / path), default_timeout=30)
        at.session_state["interview_job"] = jid
        at.run()
        assert not at.exception, at.exception
    _clear_cache()


def test_tutor_page_with_plan(make_app, cfg, monkeypatch):
    from tests.test_tutor import _tutor_app
    app = _tutor_app(make_app)
    pid = app.create_learning_plan({"skills": [{"skill": "terraform", "level": "Desde cero"}], "hours": 5,
                                    "target_date": "2027-01-15", "styles": ["Videos"],
                                    "origin": {"kind": "mercado", "label": ""}})
    app.set_task_done(pid, "s1t1", True)
    app.tutor_chat(pid, "¿Qué sigue?")
    app.db.close()
    monkeypatch.setenv("LAZARUS_DATA_DIR", str(cfg["paths"]["data"]))
    monkeypatch.setenv("PATH", "")
    _clear_cache()
    at = AppTest.from_file(str(ROOT / "pages/10_Tutor.py"), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Infra de un blog" in text and "watch?v=abc123" in text
    assert [c.value for c in at.checkbox] == [True, False, False]  # 1 de 3 tareas hechas
    # nuevo plan: el formulario de preguntas aparece con las habilidades del mercado
    at.selectbox[0].set_value(None).run()
    assert not at.exception, at.exception
    _clear_cache()
