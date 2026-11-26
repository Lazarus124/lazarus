#!/usr/bin/env bash
# Construye dist/Lazarus-Setup-<versión>.exe desde Linux.
# Requisitos: curl, tar, zip, python3 con pip, makensis (paquete nsis).
# Uso: installer/build.sh [carpeta_de_trabajo]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$HOME/lazarus-build}"
PY_RELEASE="20261124"
PY_VERSION="3.12.16"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PY_RELEASE}/cpython-${PY_VERSION}%2B${PY_RELEASE}-x86_64-pc-windows-msvc-install_only.tar.gz"
VERSION="$(python3 -c "import re,sys;print(re.search(r'__version__ = \"(.+)\"', open(sys.argv[1]).read()).group(1))" "$ROOT/lazarus/__init__.py")"
MAKENSIS="${MAKENSIS:-makensis}"

mkdir -p "$WORK"
STAGE="$WORK/stage"
rm -rf "$STAGE"
mkdir -p "$STAGE/app"

echo "== Python ${PY_VERSION} para Windows"
[ -f "$WORK/py.tar.gz" ] || curl -fsSL -o "$WORK/py.tar.gz" "$PY_URL"
tar xzf "$WORK/py.tar.gz" -C "$STAGE"

echo "== Librerías (wheels win_amd64 cp312)"
python3 -m pip install -q --target "$STAGE/python/Lib/site-packages" \
  --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 \
  --only-binary=:all: -r "$ROOT/installer/requirements-win.txt"

echo "== Limpieza"
find "$STAGE/python" -name "*.pdb" -delete
rm -rf "$STAGE/python/Lib/test" "$STAGE/python/Lib/idlelib" "$STAGE/python/Lib/tkinter" \
       "$STAGE/python/Lib/turtledemo" "$STAGE/python/tcl" "$STAGE/python/include" "$STAGE/python/libs" \
       "$STAGE/python/Lib/site-packages/bin" "$STAGE/python/Lib/site-packages/share"
find "$STAGE/python/Lib/site-packages" -type d -name tests -prune -exec rm -rf {} +
find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} +

echo "== App"
cp -r "$ROOT/app.py" "$ROOT/launcher.py" "$ROOT/config.toml" "$ROOT/README.md" \
      "$ROOT/lazarus" "$ROOT/pages" "$ROOT/data" "$ROOT/.streamlit" "$STAGE/app/"
find "$STAGE/app" -type d -name __pycache__ -prune -exec rm -rf {} +

echo "== Payload (zip)"
rm -f "$WORK/payload.zip"
( cd "$STAGE" && zip -q -r -X -6 "$WORK/payload.zip" python app )

echo "== Instalador ${VERSION}"
mkdir -p "$ROOT/dist"
OUT="$WORK/Lazarus-Setup-${VERSION}.exe"
( cd "$ROOT/installer" && "$MAKENSIS" -V2 -DVERSION="$VERSION" -DPAYLOAD="$WORK/payload.zip" -DOUTFILE="$OUT" lazarus.nsi )
cp "$OUT" "$ROOT/dist/"
ls -lh "$ROOT/dist/Lazarus-Setup-${VERSION}.exe"
