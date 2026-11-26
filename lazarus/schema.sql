CREATE TABLE IF NOT EXISTS cv (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cv_profile (
    cv_id INTEGER PRIMARY KEY REFERENCES cv(id),
    skills_json TEXT NOT NULL,
    seniority TEXT,
    profile_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search (
    id INTEGER PRIMARY KEY,
    keyword TEXT NOT NULL,
    location TEXT,
    country TEXT,
    sources_json TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    dedup_key TEXT,
    source TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    country TEXT,
    description TEXT NOT NULL,
    posted_at TEXT,
    fetched_at TEXT NOT NULL,
    duplicate_of INTEGER REFERENCES job(id),
    analysis_status TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | not_job | failed
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_dedup ON job(dedup_key);
CREATE TABLE IF NOT EXISTS search_result (
    search_id INTEGER NOT NULL REFERENCES search(id),
    job_id INTEGER NOT NULL REFERENCES job(id),
    PRIMARY KEY (search_id, job_id)
);
CREATE TABLE IF NOT EXISTS job_analysis (
    job_id INTEGER PRIMARY KEY REFERENCES job(id),
    is_job_posting INTEGER NOT NULL,
    skills_required_json TEXT NOT NULL,
    skills_nice_json TEXT NOT NULL,
    seniority TEXT,
    modality TEXT,
    country TEXT,
    city TEXT,
    language TEXT,
    years_min INTEGER,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match (
    id INTEGER PRIMARY KEY,
    cv_id INTEGER NOT NULL REFERENCES cv(id),
    job_id INTEGER NOT NULL REFERENCES job(id),
    search_country TEXT,
    score INTEGER NOT NULL,
    breakdown_json TEXT NOT NULL,
    reasons_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (cv_id, job_id)
);
CREATE TABLE IF NOT EXISTS cover_letter (
    id INTEGER PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES match(id),
    language TEXT,
    body_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY,
    markdown TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY,
    service TEXT NOT NULL,      -- brightdata | firecrawl
    operation TEXT NOT NULL,
    units INTEGER NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS domain (
    id INTEGER PRIMARY KEY,
    host TEXT NOT NULL UNIQUE,
    country TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    is_base INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,       -- running | ok | error
    params_json TEXT,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS run_step (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run(run_id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms INTEGER,
    data_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_step_run ON run_step(run_id);
CREATE TABLE IF NOT EXISTS setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
