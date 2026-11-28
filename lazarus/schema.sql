CREATE TABLE IF NOT EXISTS cv (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    file_blob BLOB,             -- archivo original (PDF o DOCX) para copiarlo al postularse
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
    remote INTEGER NOT NULL DEFAULT 0,
    freshness TEXT,             -- day | 3days | week | month (vacío = cualquier fecha)
    modalities TEXT,            -- JSON: ["remote","hybrid","onsite"] (vacío = cualquiera)
    part_time INTEGER NOT NULL DEFAULT 0,
    level TEXT,                 -- nivel buscado: intern | junior | mid | senior | lead (vacío = cualquiera)
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
    closed INTEGER NOT NULL DEFAULT 0,                -- 1 = la posición ya no recibe postulaciones
    closed_checked_at TEXT,
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
    posted_on TEXT,             -- fecha de publicación (AAAA-MM-DD) si se conoce
    employment_type TEXT,       -- full_time | part_time | contract | internship | unknown
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
CREATE TABLE IF NOT EXISTS company_research (
    company_key TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tailored_cv (
    id INTEGER PRIMARY KEY,
    cv_id INTEGER NOT NULL REFERENCES cv(id),
    job_id INTEGER NOT NULL REFERENCES job(id),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_prep (
    id INTEGER PRIMARY KEY,
    cv_id INTEGER NOT NULL REFERENCES cv(id),
    job_id INTEGER NOT NULL REFERENCES job(id),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_stage (
    cv_id INTEGER NOT NULL REFERENCES cv(id),
    job_id INTEGER NOT NULL REFERENCES job(id),
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 99,
    status TEXT NOT NULL DEFAULT 'pendiente',   -- pendiente | hecha
    notes TEXT NOT NULL DEFAULT '',
    result_json TEXT,                           -- preparación a fondo de la etapa
    updated_at TEXT NOT NULL,
    PRIMARY KEY (cv_id, job_id, name)
);
CREATE TABLE IF NOT EXISTS job_tracking (
    job_id INTEGER PRIMARY KEY REFERENCES job(id),
    status TEXT NOT NULL,       -- favorito | aplicado | no_me_gusta | no_mostrar
    notes TEXT NOT NULL DEFAULT '',
    applied_at TEXT,
    files_json TEXT,            -- copias guardadas en la carpeta de aplicaciones
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_plan (
    id INTEGER PRIMARY KEY,
    cv_id INTEGER REFERENCES cv(id),
    inputs_json TEXT NOT NULL,      -- habilidades, niveles, horas, fecha, estilo, origen
    plan_json TEXT NOT NULL,
    resources_json TEXT NOT NULL DEFAULT '{}',  -- task_id -> recursos verificados
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_progress (
    plan_id INTEGER NOT NULL REFERENCES learning_plan(id),
    task_id TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (plan_id, task_id)
);
CREATE TABLE IF NOT EXISTS tutor_message (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES learning_plan(id),
    role TEXT NOT NULL,             -- user | lazarus
    content TEXT NOT NULL,
    videos_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
