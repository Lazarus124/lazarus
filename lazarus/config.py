"""Lee config.toml y .env."""
from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load(root: Path = ROOT, data_dir: Path | None = None) -> dict:
    load_dotenv(root / ".env")
    with open(root / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    data = Path(data_dir or os.getenv("LAZARUS_DATA_DIR") or Path.home() / ".lazarus")
    cfg["paths"] = {
        "root": root,
        "data": data,
        "db": data / "lazarus.db",
        "logs": data / "logs",
        "domains_base": root / "data" / "domains_base.toml",
    }
    cfg["keys"] = {
        "firecrawl": os.getenv("FIRECRAWL_API_KEY", "").strip(),
        "brightdata": os.getenv("BRIGHTDATA_API_KEY", "").strip(),
    }
    if os.getenv("LAZARUS_DEBUG") == "1":
        cfg["logging"]["debug"] = True
    return cfg


def load_domains_base(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        return tomllib.load(f).get("domain", [])
