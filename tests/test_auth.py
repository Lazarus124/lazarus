import io
import json
from types import SimpleNamespace

from lazarus import claude_client as cc


def _fake_which(monkeypatch):
    monkeypatch.setattr(cc, "resolve_binary", lambda b="claude": "/bin/claude")


def test_auth_status_logged_in(monkeypatch):
    _fake_which(monkeypatch)
    out = {"loggedIn": True, "authMethod": "claude.ai", "email": "ana@example.com"}
    r = cc.auth_status(runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr=""))
    assert r == {"supported": True, "logged_in": True, "email": "ana@example.com", "method": "claude.ai", "detail": ""}


def test_auth_status_logged_out_and_unsupported(monkeypatch):
    _fake_which(monkeypatch)
    r = cc.auth_status(runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout='{"loggedIn": false}', stderr=""))
    assert r["supported"] and not r["logged_in"]
    r = cc.auth_status(runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="error: unknown command 'auth'"))
    assert not r["supported"] and not r["logged_in"]


def test_login_process_reads_url(monkeypatch):
    _fake_which(monkeypatch)
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            calls.append(cmd)
            self.stdout = io.StringIO("Opening browser...\nIf it did not open: https://claude.ai/oauth/authorize?x=1\n")
            self._rc = None

        def poll(self):
            return self._rc

        def kill(self):
            self._rc = -9

    lp = cc.LoginProcess(popen=FakePopen)
    import time
    for _ in range(50):
        if lp.urls():
            break
        time.sleep(0.01)
    assert calls[0][1:] == ["auth", "login", "--claudeai"]
    assert lp.urls() == ["https://claude.ai/oauth/authorize?x=1"]
    assert not lp.done
    lp.cancel()
    assert lp.done


def test_test_call_reports_auth_error(monkeypatch):
    _fake_which(monkeypatch)
    out = {"is_error": True, "subtype": "success", "result": "Failed to authenticate: OAuth session expired"}
    r = cc.test_call(runner=lambda *a, **k: SimpleNamespace(returncode=1, stdout=json.dumps(out), stderr=""))
    assert not r["ok"] and "OAuth" in r["message"]
