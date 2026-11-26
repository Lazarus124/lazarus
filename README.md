# Lazarus

Aplicación web local para buscar empleo con IA. Nombre provisional.

Lazarus busca vacantes, las compara con su CV, escribe cartas de presentación y muestra métricas del mercado.
Lazarus nunca aplica por usted.

## Instalar en Windows (recomendado)

1. Ejecute `dist/Lazarus-Setup-0.1.5.exe`. No necesita permisos de administrador.
   Windows SmartScreen puede advertir que el instalador no está firmado: elija **Más información → Ejecutar de todas formas**.
2. Abra **Lazarus** desde el menú Inicio o el escritorio. El navegador abre la app.
3. En **Configuración**, pegue las claves de Firecrawl y Bright Data. Se guardan cifradas con Windows (DPAPI).
4. Requisito aparte: Claude Code instalado. Si no hay sesión, la app muestra el botón «Iniciar sesión en Claude».

El instalador incluye Python 3.12 y todas las librerías. Se instala en `%LOCALAPPDATA%\Programs\Lazarus`.
Desinstalar no borra sus datos (`%USERPROFILE%\.lazarus`).

Para reconstruir el instalador desde Linux: `installer/build.sh` (requiere `nsis`, `zip`, `curl` y `python3`).

## Requisitos (desarrollo)

- Python 3.10 o superior.
- Claude Code instalado y con sesión iniciada (`claude --version` responde).
  En Windows, use el instalador nativo (`claude.exe`). Un `claude.cmd` de npm puede fallar con argumentos JSON.
- Una key de Firecrawl y una key de Bright Data (planes gratis). Se cargan en **Configuración**.

## Inicio rápido

```powershell
cd lazarus
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py              # abre http://localhost:8501
# Cargue las claves en Configuración (o, solo para desarrollo, en .env)
```

PRECAUCIÓN: no cree `.venv` dentro de una carpeta sincronizada (OneDrive, Dropbox) si puede evitarlo.
La sincronización de miles de archivos hace lenta la instalación.

## Datos

La base SQLite y los logs están en `~/.lazarus` (Windows: `C:\Users\<usuario>\.lazarus`).
Esta carpeta está fuera del repositorio y fuera de OneDrive: la sincronización puede dañar una base SQLite abierta.
Para usar otra carpeta, defina `LAZARUS_DATA_DIR` en `.env`.

## Configuración

- **Configuración** (en la app): claves de API, `dataset_id` de Bright Data y ruta de `claude`.
- `.env`: opcional, solo para desarrollo. Nunca lo suba a GitHub.
- `config.toml`: límites, timeouts, datasets de Bright Data, retención de logs.
- `data/domains_base.toml`: lista base de dominios para Firecrawl.

Antes de usar Indeed y Glassdoor, copie su `dataset_id` del panel de Bright Data en **Configuración**.

## Pruebas

```bash
pytest -q
```

Las pruebas no usan red ni `claude`. Usan fakes y fixtures.

## Logs y troubleshooting

Cada acción es una corrida con un `run_id`. Los errores en la UI muestran el `run_id` corto.

1. Copie el `run_id` del mensaje de error.
2. Abra la página **Corridas** y busque la corrida.
3. Lea el paso con estado `error`.
4. Si la causa no está clara, active el modo debug en **Configuración** y repita la acción.
5. Exporte la corrida (ZIP) si necesita ayuda.

ADVERTENCIA: el modo debug guarda el texto del CV en `logs/debug/`. Desactívelo al terminar.

## Estructura

```
app.py, pages/         UI de Streamlit (sin lógica de negocio)
lazarus/services.py    casos de uso que llama la UI
lazarus/claude_client  única puerta a claude -p
lazarus/sources/       Bright Data y Firecrawl
lazarus/normalize.py   URLs, skills y duplicados
lazarus/scoring.py     score determinista
lazarus/metrics.py     métricas de mercado
lazarus/runlog.py      logs de corridas y pasos
tests/                 pytest
```
