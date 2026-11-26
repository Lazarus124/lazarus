"""Score determinista de 0 a 100. Sin llamadas a Claude."""
from __future__ import annotations

LEVELS = ["intern", "junior", "mid", "senior", "lead"]
WEIGHTS = {"required": 60, "nice": 15, "seniority": 15, "location": 10}


def score(cv_skills, cv_seniority, req, nice, job_seniority, job_modality, job_country, search_country):
    cv = set(cv_skills or [])
    req, nice = list(req or []), list(nice or [])

    if req:
        req_cov = sum(1 for s in req if s in cv) / len(req)
    else:
        req_cov = 0.5  # la vacante no lista skills: valor neutro
    nice_cov = (sum(1 for s in nice if s in cv) / len(nice)) if nice else 1.0

    if not job_seniority or job_seniority == "unknown" or cv_seniority not in LEVELS:
        sen_pts = 8
    elif job_seniority not in LEVELS:
        sen_pts = 8
    else:
        diff = abs(LEVELS.index(job_seniority) - LEVELS.index(cv_seniority))
        sen_pts = 15 if diff == 0 else 8 if diff == 1 else 0

    remote = job_modality == "remote"
    same_country = bool(job_country and search_country and job_country.upper() == search_country.upper())
    loc_pts = 10 if (remote or same_country) else 0

    breakdown = {
        "required": round(WEIGHTS["required"] * req_cov, 1),
        "nice": round(WEIGHTS["nice"] * nice_cov, 1),
        "seniority": sen_pts,
        "location": loc_pts,
        "skills_matched": sorted(s for s in req + nice if s in cv),
        "skills_missing_required": [s for s in req if s not in cv],
        "skills_missing_nice": [s for s in nice if s not in cv],
        "required_listed": bool(req),
    }
    total = round(breakdown["required"] + breakdown["nice"] + sen_pts + loc_pts)
    return max(0, min(100, total)), breakdown
