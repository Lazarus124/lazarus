"""Métricas de mercado con las vacantes ya guardadas. Sin llamadas de red."""
from __future__ import annotations

import json

import pandas as pd

from .db import DB

INSUFFICIENT = "muestra insuficiente"


def load_frame(db: DB, country: str | None = None, search_id: int | None = None,
               since: str | None = None) -> pd.DataFrame:
    sql = """
        SELECT j.id, j.source, j.fetched_at, a.*
        FROM job j JOIN job_analysis a ON a.job_id = j.id
        WHERE j.duplicate_of IS NULL AND a.is_job_posting = 1
    """
    params: list = []
    if country:
        sql += " AND a.country = ?"
        params.append(country)
    if search_id:
        sql += " AND j.id IN (SELECT job_id FROM search_result WHERE search_id = ?)"
        params.append(search_id)
    if since:
        sql += " AND j.fetched_at >= ?"
        params.append(since)
    df = pd.DataFrame(db.query(sql, params))
    if df.empty:
        return df
    df["skills_required"] = df["skills_required_json"].map(json.loads)
    df["skills_nice"] = df["skills_nice_json"].map(json.loads)
    return df


def top_skills(df: pd.DataFrame, kind: str = "required", n: int = 20) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["skill", "vacantes", "porcentaje"])
    col = "skills_required" if kind == "required" else "skills_nice"
    exploded = df[["id", col]].explode(col).dropna().drop_duplicates()
    counts = exploded[col].value_counts().head(n)
    return pd.DataFrame({"skill": counts.index, "vacantes": counts.values,
                         "porcentaje": (counts.values / len(df) * 100).round(1)})


def gap(df: pd.DataFrame, cv_skills: list[str], threshold: float = 0.2) -> pd.DataFrame:
    top = top_skills(df, "required", n=200)
    if top.empty:
        return top
    cv = set(cv_skills or [])
    out = top[(top["porcentaje"] >= threshold * 100) & (~top["skill"].isin(cv))]
    return out.reset_index(drop=True)


def distribution(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Conteo de `col` (seniority o modality) por país."""
    if df.empty:
        return pd.DataFrame()
    d = df.assign(country=df["country"].fillna("?"), value=df[col].fillna("unknown"))
    return d.pivot_table(index="country", columns="value", values="id", aggfunc="count", fill_value=0)


def salaries(df: pd.DataFrame, min_n: int = 5) -> pd.DataFrame:
    cols = ["país", "moneda", "periodo", "n", "p25", "mediana", "p75"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    s = df.dropna(subset=["salary_currency", "salary_period"]).copy()
    s = s[s["salary_min"].notna() | s["salary_max"].notna()]
    if s.empty:
        return pd.DataFrame(columns=cols)
    s["mid"] = s[["salary_min", "salary_max"]].mean(axis=1, skipna=True)
    rows = []
    for (country, cur, per), g in s.groupby([s["country"].fillna("?"), "salary_currency", "salary_period"]):
        n = len(g)
        if n < min_n:
            rows.append([country, cur, per, n, INSUFFICIENT, INSUFFICIENT, INSUFFICIENT])
        else:
            q = g["mid"].quantile([0.25, 0.5, 0.75]).round(0).tolist()
            rows.append([country, cur, per, n, *q])
    return pd.DataFrame(rows, columns=cols)
