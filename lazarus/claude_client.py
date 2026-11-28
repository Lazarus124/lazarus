"""Única puerta a `claude -p`.

El prompt y los datos van por stdin. Claude corre sin herramientas y en una
carpeta temporal vacía. La salida se valida con --json-schema.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from .runlog import Run

HERE = Path(__file__).parent
# En Windows, sin esta bandera cada llamada abre una ventana de consola (la app corre con pythonw.exe).
NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
DISALLOWED_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,NotebookEdit,Task"


class ClaudeError(Exception):
    pass


class ClaudeAuthError(ClaudeError):
    """La sesión de Claude Code no es válida. Reintentar no sirve."""


AUTH_HINT = "La sesión de Claude venció. Use el botón «Iniciar sesión en Claude» y repita la acción."
AUTH_MARKERS = ("authenticate", "oauth", "/login", "not logged in", "invalid api key")


def load_prompt(task: str) -> str:
    return (HERE / "prompts" / f"{task}.md").read_text(encoding="utf-8")


def load_schema(task: str) -> dict:
    return json.loads((HERE / "schemas" / f"{task}.json").read_text(encoding="utf-8"))


def workdir() -> Path:
    """Carpeta vacía y fija donde corre `claude -p`.

    No se usa una carpeta temporal por llamada: en Windows, claude.exe (o un proceso hijo)
    puede seguir usando la carpeta al terminar y el borrado falla con WinError 32.
    """
    d = Path(tempfile.gettempdir()) / "lazarus-claude"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_binary(binary: str = "claude") -> str | None:
    """Busca la CLI: ruta configurada, PATH y ubicaciones típicas de Windows."""
    if binary and Path(binary).is_file():
        return str(Path(binary))
    found = shutil.which(binary or "claude")
    if found:
        return found
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / "claude.exe",                       # instalador nativo
        Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local")) / "Programs" / "claude" / "claude.exe",
        Path(os.getenv("APPDATA", home / "AppData" / "Roaming")) / "npm" / "claude.cmd",  # npm
        home / ".claude" / "local" / "claude",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


class ClaudeClient:
    # Tareas que generan textos largos: necesitan más tiempo y no se reintentan si se agota.
    LONG_TASKS = {"interview_prep", "interview_stage", "tailor_cv", "company_research", "cover_letter",
                  "learning_plan", "learning_resources"}

    def __init__(self, binary: str = "claude", timeout: int = 120, retries: int = 1, runner=subprocess.run,
                 long_timeout: int = 360):
        self.binary = binary
        self.timeout = timeout
        self.long_timeout = long_timeout
        self.retries = retries
        self.runner = runner

    def command(self, schema: dict) -> list[str]:
        exe = resolve_binary(self.binary) or self.binary
        return [
            exe, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema, separators=(",", ":")),
            "--disallowedTools", DISALLOWED_TOOLS,
        ]

    def run(self, task: str, data: str, run: Run) -> dict:
        prompt = load_prompt(task)
        schema = load_schema(task)
        stdin = f"{prompt}\n\n{data}"
        cmd = self.command(schema)
        long = task in self.LONG_TASKS
        timeout = max(self.timeout, self.long_timeout) if long else self.timeout
        last: Exception | None = None
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                with run.step(f"claude.{task}", attempt=attempt, input_chars=len(stdin), timeout_s=timeout) as st:
                    return self._call(cmd, stdin, st, run, task, attempt, schema, timeout)
            except ClaudeAuthError:
                raise
            except subprocess.TimeoutExpired as exc:
                last = exc
                if long:  # reintentar duplicaría la espera sin cambiar el resultado
                    raise ClaudeError(f"Claude tardó más de {timeout // 60} minutos en responder. "
                                      "Intente de nuevo en unos minutos.") from exc
            except (ClaudeError, json.JSONDecodeError, OSError) as exc:
                last = exc
        if isinstance(last, subprocess.TimeoutExpired):
            raise ClaudeError(f"Claude tardó más de {timeout} segundos en responder ({attempts} intentos).") from last
        raise ClaudeError(f"{task} falló después de {attempts} intentos: {type(last).__name__}: {last}") from last

    def _call(self, cmd, stdin, st, run, task, attempt, schema, timeout=None) -> dict:
        run.debug_dump(f"{task}-{attempt}-stdin.txt", stdin)
        proc = self.runner(
            cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
            timeout=timeout or self.timeout, cwd=str(workdir()), **NO_WINDOW,
        )
        run.debug_dump(f"{task}-{attempt}-stdout.txt", proc.stdout)
        run.debug_dump(f"{task}-{attempt}-stderr.txt", proc.stderr)
        st.set(exit_code=proc.returncode, output_chars=len(proc.stdout or ""))
        if proc.returncode != 0 and not proc.stdout:
            st.set(stderr_tail=(proc.stderr or "")[-2000:])
            raise ClaudeError(f"exit code {proc.returncode}")
        out = json.loads(proc.stdout)
        if not isinstance(out, dict):
            raise ClaudeError("la salida de claude no es un objeto JSON")
        st.set(duration_api_ms=out.get("duration_api_ms"), num_turns=out.get("num_turns"),
               subtype=out.get("subtype"), out_keys=sorted(out.keys()))
        if out.get("is_error"):
            # Con is_error, "result" trae el mensaje de error de Claude Code (login, límite de uso, API).
            message = str(out.get("result") or "").strip()[:500]
            st.set(stderr_tail=(proc.stderr or "")[-2000:], error_message=message)
            if any(m in message.lower() for m in AUTH_MARKERS):
                raise ClaudeAuthError(f"{AUTH_HINT} (Detalle: {message})")
            raise ClaudeError(f"claude devolvió un error: {message or 'sin detalle'} (subtype={out.get('subtype')})")
        result = out.get("structured_output")
        if result is not None:
            st.set(parsed_from="structured_output")
        else:
            # Algunas versiones de Claude Code no completan structured_output aunque acepten
            # --json-schema. En ese caso se lee el JSON del campo "result".
            text = out.get("result") or ""
            st.set(result_chars=len(text))
            result = extract_json(text)
            if result is None:
                raise ClaudeError(f"respuesta sin structured_output ni JSON en result (subtype={out.get('subtype')})")
            st.set(parsed_from="result")
        problems = validate(result, schema)
        if problems:
            st.set(schema_errors=problems[:5])
            raise ClaudeError("la respuesta no cumple el schema: " + "; ".join(problems[:3]))
        return result


def extract_json(text: str):
    """Devuelve el primer objeto JSON del texto (acepta bloques ```json)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    if start != -1:
        candidates.append(text[start:])
    decoder = json.JSONDecoder()
    for c in candidates:
        try:
            obj, _ = decoder.raw_decode(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}


def validate(value, schema: dict, path: str = "$") -> list[str]:
    """Validación mínima de JSON Schema: type, required, enum, properties, items."""
    errors: list[str] = []
    types = schema.get("type")
    if types:
        types = types if isinstance(types, list) else [types]
        ok = any(value is None if t == "null" else
                 (isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool)))
                 for t in types)
        if not ok:
            return [f"{path}: tipo {type(value).__name__}, se esperaba {types}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: valor {value!r} fuera de {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: falta '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))
    return errors


def health(binary: str = "claude", runner=subprocess.run) -> dict:
    """Comprueba que la CLI existe y responde a --version."""
    exe = resolve_binary(binary)
    if not exe:
        return {"ok": False, "path": None, "version": None,
                "error": "No encuentro 'claude' en el PATH. Instale Claude Code y abra una terminal nueva."}
    warning = None
    if exe.lower().endswith((".cmd", ".bat")):
        warning = ("'claude' es un script .cmd. Los argumentos con comillas pueden fallar. "
                   "Recomendado: instalador nativo de Claude Code (claude.exe).")
    try:
        proc = runner([exe, "--version"], capture_output=True, text=True, timeout=30, **NO_WINDOW)
        return {"ok": proc.returncode == 0, "path": exe, "version": (proc.stdout or proc.stderr).strip(),
                "warning": warning, "error": None if proc.returncode == 0 else proc.stderr.strip()}
    except Exception as exc:  # noqa: BLE001 - se muestra al usuario
        return {"ok": False, "path": exe, "version": None, "warning": warning, "error": str(exc)}


# ------------------------------------------------------------------ sesión de Claude Code
def auth_status(binary: str = "claude", runner=subprocess.run) -> dict:
    """Estado de la sesión con `claude auth status --json` (sin consumo). Requiere Claude Code 2.1.41+."""
    exe = resolve_binary(binary)
    if not exe:
        return {"supported": False, "logged_in": False, "email": None, "detail": "No encuentro 'claude'."}
    try:
        proc = runner([exe, "auth", "status", "--json"], capture_output=True, text=True, timeout=30, **NO_WINDOW)
    except Exception as exc:  # noqa: BLE001
        return {"supported": False, "logged_in": False, "email": None, "detail": str(exc)}
    text = (proc.stdout or "").strip()
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {}
    if not data and proc.returncode != 0 and "unknown" in (proc.stderr or "").lower():
        return {"supported": False, "logged_in": False, "email": None,
                "detail": "Esta versión de Claude Code no tiene 'claude auth'. Actualícela."}
    logged = data.get("loggedIn", data.get("logged_in", proc.returncode == 0))
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    email = data.get("email") or data.get("emailAddress") or account.get("email") or account.get("emailAddress")
    return {"supported": True, "logged_in": bool(logged), "email": email,
            "method": data.get("authMethod") or data.get("auth_method"), "detail": (proc.stderr or "").strip()[:300]}


class LoginProcess:
    """`claude auth login` en segundo plano: abre el navegador y espera la aprobación del usuario."""

    def __init__(self, binary: str = "claude", popen=subprocess.Popen):
        exe = resolve_binary(binary)
        if not exe:
            raise ClaudeError("No encuentro 'claude'. Instale Claude Code.")
        self.lines: list[str] = []
        self.proc = popen([exe, "auth", "login", "--claudeai"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())

    @property
    def done(self) -> bool:
        return self.proc.poll() is not None

    @property
    def returncode(self) -> int | None:
        return self.proc.poll()

    def urls(self) -> list[str]:
        return [u for line in self.lines for u in re.findall(r"https://\S+", line)]

    def cancel(self) -> None:
        if not self.done:
            self.proc.kill()


def test_call(binary: str = "claude", runner=subprocess.run, timeout: int = 90) -> dict:
    """Llamada mínima real a `claude -p` para confirmar que la sesión funciona."""
    exe = resolve_binary(binary)
    if not exe:
        return {"ok": False, "message": "No encuentro 'claude'."}
    try:
        proc = runner([exe, "-p", "--output-format", "json"], input="Responde solo: ok", capture_output=True,
                      text=True, encoding="utf-8", timeout=timeout, cwd=str(workdir()), **NO_WINDOW)
        out = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    if out.get("is_error"):
        return {"ok": False, "message": str(out.get("result") or "error sin detalle")[:300]}
    return {"ok": True, "message": "Claude responde correctamente."}
