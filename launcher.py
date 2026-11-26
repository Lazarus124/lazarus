"""Lanzador de Lazarus para el instalador de Windows.

- Una sola instancia: si Lazarus ya corre, solo abre el navegador.
- Streamlit escucha solo en 127.0.0.1 (no expone la app a la red).
- Con pythonw.exe no hay consola: la salida va a ~/.lazarus/logs/launcher.log.
"""
from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA = Path(os.getenv("LAZARUS_DATA_DIR") or Path.home() / ".lazarus")
PORT_FILE = DATA / "launcher.port"
PORTS = range(8501, 8521)


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as r:
            return r.read().strip() == b"ok"
    except OSError:
        return False


def app_version() -> str:
    text = (APP_DIR / "lazarus" / "__init__.py").read_text(encoding="utf-8")
    return text.split('__version__ = "')[1].split('"')[0]


def running_port() -> int | None:
    """Puerto de una instancia sana de la MISMA versión. Cierra instancias de otra versión."""
    try:
        parts = PORT_FILE.read_text().split()
        port = int(parts[0])
    except (OSError, ValueError, IndexError):
        return None
    if not healthy(port):
        return None
    pid = int(parts[1]) if len(parts) > 1 else None
    version = parts[2] if len(parts) > 2 else None
    if version == app_version():
        return port
    # Quedó abierta una versión anterior (por ejemplo, después de actualizar): se cierra.
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(20):
            if not healthy(port):
                break
            time.sleep(0.5)
    return None


def free_port() -> int:
    for port in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No hay puertos libres entre 8501 y 8520")


def open_when_ready(port: int) -> None:
    for _ in range(240):  # hasta 2 minutos en el primer arranque
        if healthy(port):
            webbrowser.open(f"http://localhost:{port}")
            return
        time.sleep(0.5)


def main() -> None:
    port = running_port()
    if port:
        webbrowser.open(f"http://localhost:{port}")
        return

    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.executable.lower().endswith("pythonw.exe"):
        log = open(DATA / "logs" / "launcher.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    print(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} inicio de Lazarus {app_version()} desde {APP_DIR}", flush=True)

    port = free_port()
    PORT_FILE.write_text(f"{port} {os.getpid()} {app_version()}")
    os.environ["LAZARUS_LAUNCHER"] = "1"
    os.chdir(APP_DIR)
    threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", str(APP_DIR / "app.py"),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
        "--theme.base=light",
    ]
    try:
        stcli.main()
    finally:
        try:
            PORT_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
