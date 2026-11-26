"""Humo de la UI: cada página carga sin excepciones (sin red y sin claude)."""
import pytest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent

PAGES = ["app.py", "pages/1_CV.py", "pages/2_Buscar.py", "pages/3_Vacantes.py", "pages/4_Carta.py",
         "pages/5_Mercado.py", "pages/6_Configuracion.py", "pages/7_Corridas.py"]


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
