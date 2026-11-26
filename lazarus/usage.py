"""Contador de consumo de Bright Data y Firecrawl."""
from __future__ import annotations

from datetime import datetime, timezone

from .db import DB, now


def record(db: DB, service: str, operation: str, units: int, run_id: str | None = None) -> None:
    if units:
        db.execute(
            "INSERT INTO usage_log (service, operation, units, run_id, created_at) VALUES (?,?,?,?,?)",
            (service, operation, int(units), run_id, now()),
        )


def month_total(db: DB, service: str) -> int:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    row = db.one(
        "SELECT COALESCE(SUM(units), 0) AS n FROM usage_log WHERE service = ? AND substr(created_at, 1, 7) = ?",
        (service, month),
    )
    return int(row["n"])


def status(db: DB, cfg: dict) -> dict:
    limits = {"brightdata": cfg["usage"]["brightdata_monthly"], "firecrawl": cfg["usage"]["firecrawl_monthly"]}
    out = {}
    for service, limit in limits.items():
        used = month_total(db, service)
        ratio = used / limit if limit else 0
        out[service] = {"used": used, "limit": limit, "ratio": ratio,
                        "warn": ratio >= cfg["usage"]["warn_ratio"], "blocked": ratio >= 1}
    return out


def firecrawl_search_credits(n_results: int) -> int:
    """2 créditos por cada 10 resultados, redondeo hacia arriba (mínimo 2)."""
    return max(1, -(-n_results // 10)) * 2
