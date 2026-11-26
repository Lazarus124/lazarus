import json

from lazarus.secrets import SecretStore


def test_secret_store_roundtrip(tmp_path):
    s = SecretStore(tmp_path)
    assert s.get("firecrawl") == "" and not s.has("firecrawl")
    s.set("firecrawl", "  fc-abc  ")
    assert s.get("firecrawl") == "fc-abc" and s.has("firecrawl")
    s.delete("firecrawl")
    assert not s.has("firecrawl")


def test_keys_from_ui_override_env_and_never_logged(make_app, cfg):
    app = make_app()
    assert app.key_source("firecrawl") == ".env"  # el fixture simula keys de .env
    app.save_key("firecrawl", "fc-desde-ui-SECRETA")
    assert app.cfg["keys"]["firecrawl"] == "fc-desde-ui-SECRETA"
    assert app.key_source("firecrawl") == "interfaz"
    assert app.firecrawl.api_key == "fc-desde-ui-SECRETA"
    blob = "".join(p.read_text(encoding="utf-8") for p in cfg["paths"]["logs"].glob("*.jsonl"))
    blob += json.dumps(app.db.query("SELECT * FROM run")) + json.dumps(app.db.query("SELECT * FROM run_step"))
    assert "fc-desde-ui-SECRETA" not in blob
    app.delete_key("firecrawl")
    assert app.cfg["keys"]["firecrawl"] == "fc-test"


def test_dataset_setting_enables_source(make_app):
    from lazarus.sources.brightdata_source import BrightDataSource
    app = make_app()
    app._injected["brightdata"] = False
    app.apply_settings()
    assert isinstance(app.brightdata, BrightDataSource)
    assert not app.source_status()["indeed"]["ok"]
    app.set_setting("dataset.indeed", "gd_indeed123")
    assert app.cfg["brightdata"]["datasets"]["indeed"] == "gd_indeed123"
    assert app.source_status()["indeed"]["ok"]
