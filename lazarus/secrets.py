"""Almacén de keys de API.

En Windows cifra cada key con DPAPI (CryptProtectData): solo el mismo usuario de
Windows en la misma computadora puede descifrarla. Sin dependencias externas.
En otros sistemas (desarrollo y pruebas) guarda el valor sin cifrar en un archivo
con permisos 600 y la UI muestra una advertencia.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

NAMES = ("firecrawl", "brightdata")
_lock = threading.Lock()


def scheme() -> str:
    return "dpapi" if sys.platform == "win32" else "plain"


# ------------------------------------------------------------------ DPAPI
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_wchar_p, ctypes.POINTER(DATA_BLOB),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        ok = fn(ctypes.byref(blob_in), "Lazarus", None, None, None, flags, ctypes.byref(blob_out))
    else:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        ok = fn(ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out))
    fn.restype = wintypes.BOOL
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


# ------------------------------------------------------------------ almacén
class SecretStore:
    def __init__(self, data_dir: Path | str):
        self.path = Path(data_dir) / "secrets.json"

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, content: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(content, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, name: str) -> str:
        with _lock:
            entry = self._read().get(name)
        if not entry:
            return ""
        raw = base64.b64decode(entry["value"])
        if entry["scheme"] == "dpapi":
            raw = _dpapi(raw, protect=False)
        return raw.decode("utf-8")

    def set(self, name: str, value: str) -> None:
        if name not in NAMES:
            raise ValueError(f"Key desconocida: {name}")
        value = value.strip()
        if not value:
            raise ValueError("La key está vacía")
        raw = value.encode("utf-8")
        sch = scheme()
        if sch == "dpapi":
            raw = _dpapi(raw, protect=True)
        with _lock:
            content = self._read()
            content[name] = {"scheme": sch, "value": base64.b64encode(raw).decode("ascii")}
            self._write(content)

    def delete(self, name: str) -> None:
        with _lock:
            content = self._read()
            if content.pop(name, None) is not None:
                self._write(content)

    def has(self, name: str) -> bool:
        with _lock:
            return name in self._read()
