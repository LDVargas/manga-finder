# CLAUDE.md — Manga Finder

Contexto de proyecto para Claude Code. Leer antes de cualquier tarea.

## Objetivo

Herramienta local personal para encontrar dónde leer los ~3,207 mangas exportados de ZonaTMO (sitio cerrado). Busca en MangaDex (y en el futuro en InManga y ComicK) usando fuzzy matching, verifica disponibilidad de capítulos en ES/EN, y presenta resultados en una web local.

**No es un producto. No hay usuarios externos. No hay autenticación. Uso 100% personal y local.**

## Stack actual

- Python 3.13
- FastAPI 0.115.5 + uvicorn 0.32.1
- asyncpg 0.30.0 → PostgreSQL (`MangaList` en localhost:5432, usuario `postgres`, contraseña `admin`)
- httpx 0.28.0 — cliente HTTP async
- rapidfuzz 3.10.1 — fuzzy matching de títulos
- Jinja2 3.1.4 — template HTML
- python-dotenv 1.0.1

## Arquitectura actual

```
main.py
  └─ lifespan: init_db() → parse(MANGA_LIST) → bulk_insert_mangas()
  └─ FastAPI app
       └─ router.py
            ├─ GET  /                    → index.html con stats
            ├─ GET  /api/mangas          → lista paginada y filtrada
            ├─ GET  /api/stats           → conteos por estado
            ├─ GET  /api/search/progress → estado de búsqueda en curso
            ├─ POST /api/search/start    → lanza búsqueda masiva (background task)
            ├─ POST /api/search/{id}/retry → re-busca un manga individual
            └─ GET  /api/export/csv     → descarga CSV

manga_finder/
  normalizer.py  → normalize(title) — strip accents, lowercase, remove punctuation
  parser.py      → parse(filepath) → list[MangaEntry] — dedup por título normalizado
  database.py    → get_pool(), init_db(), bulk_insert_mangas(), get_all(), update_result(), ...
  mangadex.py    → search_and_update() — busca en MangaDex, actualiza DB
```

## Flujo de datos

```
MIS_MANGAS_RESCATADOS.txt
  → parser.py: parseo línea por línea, dedup por title_normalized
  → database.py: INSERT ON CONFLICT DO NOTHING (idempotente)

Usuario → POST /api/search/start
  → router.py: _run_full_search() en background
  → database.py: get_pending(limit=10000)
  → mangadex.py: search_and_update() en batches de 50 (asyncio.gather)
     → MangaDex API: GET /manga?title=... (semaphore 4 req/s)
     → rapidfuzz: score sobre todos los títulos/altTitles
     → MangaDex API: GET /manga/{id}/aggregate (counts ES/EN)
     → database.py: update_result()
  → router.py: _search_progress actualizado (polling cada 2s desde UI)
```

## Convenciones del código

- **Async by default**: todo I/O usa `async/await` (asyncpg, httpx)
- **Sin ORM**: SQL directo con asyncpg (parametrizado, no concatenar strings)
- **Sin comentarios obvios**: solo comentar el "por qué", no el "qué"
- **Tipos explícitos**: usar type hints en todas las funciones públicas
- **Módulos planos**: sin clases innecesarias, funciones libres donde sea suficiente
- **Errores silenciados deliberadamente**: `except Exception` en el worker de búsqueda marca `search_status='error'` — no re-raise porque la búsqueda masiva no debe interrumpirse por un manga

## Reglas de desarrollo

### Seguridad
- El `.env` NUNCA debe commitearse
- `DATABASE_URL` viene siempre de `os.environ["DATABASE_URL"]` (falla ruidosamente si falta)
- No hay SQL dinámico: siempre usar parámetros `$1`, `$2`... de asyncpg
- La app corre en `127.0.0.1` (no en `0.0.0.0`): acceso solo local

### Modificaciones a la DB
- La tabla se crea con `CREATE TABLE IF NOT EXISTS` en cada arranque (idempotente)
- Las migraciones futuras deben usar `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- **NUNCA hacer DROP TABLE ni DELETE sin preguntar primero**
- Los datos de búsqueda (3,207 mangas procesados) son costosos de regenerar (~15 min)

### Proceso activo
- La app puede estar corriendo mientras se trabaja en el código
- **NO matar uvicorn, NO reiniciar PostgreSQL** sin confirmar con el usuario
- Los cambios a archivos Python requieren reinicio manual del servidor (no hay hot-reload activo)

### Estado de búsqueda
- `_search_progress` en `router.py` es **en memoria** — se pierde al reiniciar el servidor
- `search_status` en la DB persiste — la búsqueda puede reanudarse siempre
- Una búsqueda interrumpida se reanuda automáticamente con "Buscar Todo" (solo procesa `pending`)

## Comandos útiles

```bash
# Iniciar el servidor
python main.py

# Ver estado actual de la DB (PowerShell)
# Conectar a psql y ejecutar:
# SELECT search_status, COUNT(*) FROM mangas GROUP BY search_status;

# Ver logs del servidor
# Los logs van a stdout de uvicorn

# Exportar CSV
# Desde la UI: botón "Exportar CSV"
# O via curl: curl http://localhost:8000/api/export/csv -o resultados.csv
```

## Problemas conocidos / deuda técnica

1. **`get_pending` tiene `limit=500` en la firma** pero el router la llama con `limit=10000` — funciona correctamente pero la firma es engañosa
2. **`_search_progress` es en-memoria** — si el servidor cae durante una búsqueda, el progreso visual se pierde (los datos en DB están bien)
3. **`_search_task` en router.py se declara pero no se usa** — la tarea corre vía `BackgroundTasks` de FastAPI, no como asyncio.Task
4. **Sin `.gitignore`** — `.env` y `__pycache__` no están ignorados
5. **Sin tests** — no hay pytest ni fixtures
6. **Sin logging estructurado** — solo prints en startup; errores en búsqueda se silencian

## Arquitectura planificada (NO implementada aún)

### Multi-site provider pattern

El plan aprobado es agregar InManga y ComicK como fuentes adicionales de búsqueda. Cada manga se buscará en **todos los sitios en paralelo** y se guardarán **todas las fuentes encontradas**.

Ver [docs/roadmap.md](docs/roadmap.md) para el plan completo.

Estructura futura:
```
manga_finder/
  providers/
    __init__.py
    base.py        # SiteResult dataclass + SearchProvider Protocol
    mangadex.py    # MangaDex provider (refactorizar desde mangadex.py)
    inmanga.py     # InManga provider (nuevo)
    comick.py      # ComicK provider (nuevo)
```

DB: agregar columna `site_results JSONB DEFAULT '[]'` — array de resultados por sitio.

**No implementar el provider pattern hasta que la búsqueda actual en MangaDex esté completa.**

## Archivos críticos

| Archivo | Responsabilidad |
|---|---|
| [main.py](main.py) | Entry point, lifespan, startup |
| [manga_finder/mangadex.py](manga_finder/mangadex.py) | Búsqueda MangaDex, fuzzy match, semaphore |
| [manga_finder/database.py](manga_finder/database.py) | Pool, CRUD, schema |
| [manga_finder/router.py](manga_finder/router.py) | API endpoints, background search task |
| [manga_finder/parser.py](manga_finder/parser.py) | Parseo y deduplicación del .txt |
| [manga_finder/normalizer.py](manga_finder/normalizer.py) | Normalización de títulos |
| [templates/index.html](templates/index.html) | Frontend completo (HTML + JS inline) |
| [MIS_MANGAS_RESCATADOS.txt](MIS_MANGAS_RESCATADOS.txt) | Datos fuente — NO modificar |
| [.env](.env) | Credenciales DB — NO versionar |
