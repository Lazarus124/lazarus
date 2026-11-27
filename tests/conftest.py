import json
import subprocess
from types import SimpleNamespace

import pytest

from lazarus.models import RawJob

from lazarus import config
from lazarus.claude_client import ClaudeClient
from lazarus.services import Lazarus

CV_TEXT = ("María Ejemplo López\nIngeniera de soporte cloud\nExperiencia: 2 años en soporte técnico.\n"
           "Skills: AWS, Linux, Python, redes, inglés intermedio. Certificación AWS Cloud Practitioner.\n"
           "SECRETO_CV_MARCADOR")


def fake_outputs(stdin: str) -> dict:
    if stdin.startswith("Eres un analista de perfiles"):
        return {"skills": ["AWS", "Linux", "Python", "redes", "English"], "seniority": "junior",
                "years_experience": 2, "languages": ["español", "inglés"], "roles": ["soporte cloud"],
                "summary": "Ingeniera de soporte cloud junior."}
    if stdin.startswith("Eres un analista del mercado laboral"):
        if "No es vacante" in stdin:
            return {"is_job_posting": False, "title": None, "company": None, "country": None, "city": None,
                    "modality": "unknown", "seniority": "unknown", "skills_required": [], "skills_nice": [],
                    "years_min": None, "language": None, "salary": None}
        return {"is_job_posting": True, "title": None, "company": None, "country": "MX", "city": "Guadalajara",
                "modality": "remote" if "Remoto" in stdin else "onsite", "seniority": "junior",
                "skills_required": ["aws", "linux", "terraform"], "skills_nice": ["python"], "years_min": 1,
                "language": "es", "salary": {"min": 20000, "max": 30000, "currency": "MXN", "period": "month"}}
    if stdin.startswith("Eres un orientador"):
        return {"reasons": ["Domina AWS y Linux."], "risks": ["No muestra Terraform."]}
    if stdin.startswith("Eres un redactor"):
        return {"greeting": "Estimado equipo de Acme:", "paragraphs": ["P1.", "P2.", "P3."], "closing": "Saludos cordiales."}
    if stdin.startswith("Eres un analista que prepara a un candidato"):
        url = stdin.split("URL: ", 1)[1].split("\n", 1)[0] if "URL: " in stdin else ""
        return {"summary": "Acme es una empresa de software.", "what_they_do": "Software cloud.",
                "size_and_locations": "200 empleados, México.", "products_and_tech": ["aws"],
                "culture_and_reviews": "Opiniones positivas.", "recent_news": [], "red_flags": [],
                "questions_to_ask": ["¿Cómo es el equipo?"], "ambiguity": None,
                "sources": [{"title": "Sitio", "url": url}, {"title": "Inventada", "url": "https://inventada.com"}]}
    if stdin.startswith("Eres un especialista en CV"):
        return {"name": "María Ejemplo López", "headline": "Soporte cloud orientada a DevOps", "contact": "maria@example.com",
                "summary": "Ingeniera de soporte cloud.", "skills": ["aws", "linux"],
                "experience": [{"role": "Soporte técnico", "company": "Empresa X", "dates": "2023-2025",
                                "bullets": ["Resolví incidentes en AWS."]}],
                "education": [{"title": "Ingeniería", "institution": "UNAM", "dates": "2022"}],
                "certifications": ["AWS Cloud Practitioner"], "languages": ["Español", "Inglés"],
                "notes_for_user": ["Falta Terraform."]}
    if stdin.startswith("Eres un coach de entrevistas laborales. Arma el plan"):
        def stage(name, q):
            return {"name": name, "interviewer": "Persona", "goal": "Validar", "format": "30 min", "evaluates": ["comunicación"],
                    "questions": [{"question": q, "why": "Porque sí.", "answer_hint": "Use su experiencia."}],
                    "tips": ["Llegue a tiempo"], "questions_to_ask": ["¿Cómo es el equipo?"]}
        return {"overview": "Proceso de 3 etapas.",
                "stages": [stage("Reclutador/a", "¿Por qué este puesto?"), stage("Hiring manager", "¿Qué es una VPC?"),
                           stage("Técnica", "Diseñe una red en AWS")],
                "topics_to_review": ["Terraform"], "points_to_clarify": []}
    if stdin.startswith("Eres un coach de entrevistas laborales. Prepara a fondo"):
        prev = stdin.split("<etapas_anteriores>", 1)[1]
        return {"focus": "Profundizar en redes" + (" (usa notas previas)" if "me fue mal en redes" in prev else ""),
                "questions": [{"question": "¿Cómo depura una VPC?", "why": "Redes.", "answer_hint": "Paso a paso.",
                               "follow_up": "¿Y con peering?"}],
                "tips": ["Dibuje la arquitectura"], "questions_to_ask": ["¿Qué stack usan?"]}
    if stdin.startswith("Eres un entrevistador experimentado"):
        return {"score": 3, "strengths": ["Clara"], "improvements": ["Dar un ejemplo"], "improved_answer": "Una VPC es..."}
    raise AssertionError("prompt desconocido")


class FakeRunner:
    def __init__(self, fail_times: int = 0, garbage: bool = False):
        self.calls = []
        self.fail_times = fail_times
        self.garbage = garbage

    def __call__(self, cmd, input=None, **kw):
        self.calls.append({"cmd": cmd, "input": input, "kw": kw})
        if self.fail_times > 0:
            self.fail_times -= 1
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))
        if self.garbage:
            return SimpleNamespace(returncode=0, stdout='{"type":"result","is_error":true,"subtype":"error"}', stderr="boom")
        out = {"type": "result", "subtype": "success", "is_error": False, "result": "",
               "structured_output": fake_outputs(input), "duration_api_ms": 10, "num_turns": 1}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


class FakeBrightData:
    def __init__(self, jobs_by_source=None, fail=None):
        self.jobs_by_source = jobs_by_source or {}
        self.fail = fail or set()
        self.calls = []

    def available(self, source):
        return True, ""

    def collect_url(self, source, url, run):
        self.calls.append(("url", source, url))
        return RawJob(source, url, "DevOps en Acme. AWS, Linux.", title="DevOps", company="Acme", country="MX")

    def search(self, source, keyword, location, country, run, remote=False):
        from lazarus.models import SourceError
        self.calls.append((source, keyword, location, country))
        with run.step(f"brightdata.{source}") as st:
            if source in self.fail:
                raise SourceError("Bright Data: tiempo agotado")
            jobs = self.jobs_by_source.get(source, [])
            st.set(records=len(jobs))
            return jobs, len(jobs)


class FakeFirecrawlClient:
    def __init__(self, results):
        self.results = results  # list of (url, title, markdown)
        self.search_calls = []
        self.scrape_calls = []

    def search(self, query, include_domains=None, limit=None):
        self.search_calls.append({"query": query, "include_domains": include_domains, "limit": limit})
        return SimpleNamespace(web=[SimpleNamespace(url=u, title=t) for u, t, _ in self.results])

    def scrape(self, url, formats=None, only_main_content=None):
        self.scrape_calls.append(url)
        md = next(m for u, _, m in self.results if u == url)
        return SimpleNamespace(markdown=md)


@pytest.fixture
def cfg(tmp_path):
    c = config.load(data_dir=tmp_path / "data")
    c["keys"] = {"firecrawl": "fc-test", "brightdata": "bd-test"}  # simula keys de .env
    c["logging"]["debug"] = False
    return c


@pytest.fixture
def make_app(cfg):
    def _make(runner=None, brightdata=None, fc_client=None):
        from lazarus.sources.firecrawl_source import FirecrawlSource
        runner = runner or FakeRunner()
        app = Lazarus(cfg, claude=ClaudeClient("claude", 5, 1, runner=runner), brightdata=brightdata or FakeBrightData())
        app.firecrawl = FirecrawlSource("fc-test", app.db, cfg["firecrawl"], client=fc_client or FakeFirecrawlClient([]))
        app._runner = runner
        return app
    return _make


def make_docx(text: str) -> bytes:
    import io
    from docx import Document
    d = Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
