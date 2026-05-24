# Arquitectura — Manga Finder

## Visión general

Aplicación web local de una sola instancia. Sin autenticación, sin multi-tenancy. Diseñada para procesar una lista estática de ~3,207 mangas una sola vez y consultar los resultados indefinidamente.

## Capas

```
┌────────────────────────────────────────────────────────┐
│  Browser (localhost:8000)                              │
│  HTML + Vanilla JS — polling, filtros, paginación      │
└───────────────────────┬────────────────────────────────┘
                        │ HTTP
┌───────────────────────▼────────────────────────────────┐
│  FastAPI (uvicorn)                                     │
│  router.py — REST API + Jinja2 template                │
│  BackgroundTasks — búsqueda masiva async               │
└──────┬────────────────────┬───────────────────────────┘
       │                    │
┌──────▼──────┐    ┌────────▼────────────────────────────┐
│ PostgreSQL  │    │  MangaDex API (api.mangadex.org)    │
│ (asyncpg)   │    │  httpx async + semaphore(4)         │
│ MangaList   │    │  rapidfuzz matching                 │
└─────────────┘    └─────────────────────────────────────┘
```

## Módulos

### `main.py` — Entry point

- Carga `.env` con `python-dotenv`
- Define `lifespan` context manager (startup/shutdown)
- En startup: `init_db()` → `parse()` → `bulk_insert_mangas()`
- Registra el router y lanza uvicorn en `127.0.0.1:8000`

### `manga_finder/normalizer.py` — Normalización

Función pura `normalize(title: str) -> str`:

1. Strip de espacios
2. Elimina sufijo ` - -` (artefacto de exportación de Firefox)
3. Lowercase
4. Elimina acentos via NFD decomposition (unicodedata)
5. Reemplaza puntuación con espacios
6. Colapsa espacios múltiples

Usada en dos contextos:
- **Deduplicación**: clave de agrupación en `parser.py`
- **Fuzzy matching**: la librería rapidfuzz compara strings normalizados

### `manga_finder/parser.py` — Parseo del archivo fuente

Lee `MIS_MANGAS_RESCATADOS.txt` línea por línea (skip 2 headers).

**Formato de cada línea:**
```
FUENTE | ESTADO | CAP | NOMBRE DEL MANGA
```

**Deduplicación:**
- Clave: `normalize(título)`
- Mismo manga aparece 2 veces: fuente "Web" (mayúsculas) y "Firefox" (minúsculas + ` - -`)
- Resolución: keep max(chapters_read), keep status más prioritario, prefer titulo "Web"
- Prioridad de status: `leido`(4) > `leyendo`(3) > `siguiendo`(2) > `pendiente`(1)

**Resultado:** `list[MangaEntry]` — 3,207 entradas únicas de 3,779 raw

### `manga_finder/database.py` — Capa de persistencia

Pool asyncpg con `min_size=2, max_size=10`. Sin ORM — SQL directo parametrizado.

**Funciones clave:**

| Función | Descripción |
|---|---|
| `get_pool()` | Lazy init del pool (singleton global) |
| `init_db()` | `CREATE TABLE IF NOT EXISTS mangas (...)` |
| `bulk_insert_mangas(entries)` | INSERT ON CONFLICT DO NOTHING — idempotente |
| `get_all(filters...)` | SELECT paginado con filtros dinámicos |
| `get_pending(limit)` | Mangas con `search_status='pending'` |
| `update_result(manga_id, ...)` | Escribe resultado de búsqueda MangaDex |
| `reset_manga(manga_id)` | Resetea a `pending` para re-búsqueda |
| `get_stats()` | Conteos por `search_status` |

**Construcción dinámica de WHERE:**
Usa un índice `idx` incrementando posiciones `$1`, `$2`... para evitar SQL injection. Los filtros se aplican solo si los parámetros tienen valor.

### `manga_finder/mangadex.py` — Cliente MangaDex

**Rate limiting:** `asyncio.Semaphore(4)` global — máximo 4 requests concurrentes a MangaDex.

**Retry:** `_request_with_retry()` — 5 intentos con backoff exponencial (1s → 2s → 4s → max 30s) en 429, 5xx, timeout, NetworkError.

**Búsqueda:**
```
search_and_update(manga_id, title, title_normalized, chapters_read)
  → Intenta primero title_normalized, luego title (si score < MIN_SCORE)
  → GET /manga?title={query}&limit=10&availableTranslatedLanguage[]=es,es-la,en
  → Para cada resultado: _best_title_score(query, manga_data)
     → fuzz.token_set_ratio + fuzz.ratio sobre title + todos los altTitles
     → toma el máximo
  → Si best_score >= 72.0 → aceptar; sino → "not_found"
  → GET /manga/{id}/aggregate?translatedLanguage[]=es,es-la (y luego en)
  → chapters_ok = (chapters_read == 0) OR (max(chap_es, chap_en) >= floor(chapters_read))
  → update_result(...)
```

**Edge case documentado:** La API de MangaDex retorna `volumes: []` (lista vacía) cuando no hay capítulos en un idioma, no `{}`. El código maneja esto con `if not isinstance(volumes, dict): continue`.

### `manga_finder/router.py` — API y orquestación de búsqueda

**Estado de búsqueda:** Dictado global `_search_progress` en memoria.

```python
_search_progress = {
    "running": bool,
    "total": int,
    "done": int,
    "found": int,
    "not_found": int,
    "errors": int,
}
```

**`_run_full_search()`:**
- Obtiene todos los mangas `pending`
- Procesa en batches de 50 con `asyncio.gather`
- Cada tarea: `search_and_update()` → actualiza `_search_progress`
- Errores se capturan por individuo y marcan `search_status='error'`

**`_search_single(manga_id)`:** Para retry individual. Reutiliza `search_and_update()`.

### `templates/index.html` — Frontend

SPA-like con Vanilla JS. Sin frameworks. Comunicación via `fetch()` al API REST.

**Interacciones:**
- **Carga inicial:** `loadPage(0)` → `GET /api/mangas`
- **Filtros:** cada cambio → `loadPage(0)` (debounce 400ms en búsqueda de texto)
- **Búsqueda masiva:** `startSearch()` → `POST /api/search/start` → `pollProgress()` cada 2s
- **Paginación:** `loadPage(offset)` con tamaño configurable (50/100/200)
- **Stats en header:** actualizadas en `refreshStats()` al finalizar búsqueda

## Diagrama de base de datos

```
mangas
├─ id                    SERIAL PK
├─ title                 TEXT NOT NULL
├─ title_normalized      TEXT UNIQUE NOT NULL  ← clave de dedup
├─ chapters_read         NUMERIC(8,1)
├─ status                TEXT                  ← leyendo|siguiendo|pendiente|leido
├─ mangadex_id           TEXT
├─ mangadex_url          TEXT
├─ match_score           NUMERIC(5,2)
├─ available_languages   JSONB                 ← ["es", "en"]
├─ chapters_available_es INTEGER
├─ chapters_available_en INTEGER
├─ chapters_ok           BOOLEAN
└─ search_status         TEXT DEFAULT 'pending' ← pending|found|not_found|error
```

## Decisiones arquitectónicas

### ¿Por qué PostgreSQL y no SQLite?
El sistema ya tiene PostgreSQL instalado con la base de datos `MangaList`. asyncpg ofrece mejor rendimiento para operaciones concurrentes que aiosqlite.

### ¿Por qué fuzzy matching y no búsqueda exacta?
Los títulos en ZonaTMO no siempre coinciden exactamente con los títulos en MangaDex. Los mangas tienen títulos en varios idiomas, con variaciones de capitalización y caracteres especiales. rapidfuzz con `token_set_ratio` maneja bien estas diferencias.

### ¿Por qué batches de 50 y no toda la lista de una vez?
`asyncio.gather(*[f() for f in 3207_tasks])` crearía 3,207 coroutines simultáneas. Aunque el semaphore limita a 4 requests HTTP concurrentes, el overhead de memoria y scheduling de Python justifica procesar por batches.

### ¿Por qué Vanilla JS y no React/Vue?
Herramienta personal local. El overhead de un framework (bundler, node_modules, build step) no aporta valor para este caso de uso. La UI completa cabe en un único archivo HTML.

## Arquitectura futura planificada

Ver [roadmap.md](roadmap.md) — La arquitectura planificada introduce un **provider pattern** para búsqueda multi-sitio (InManga, ComicK). No está implementada.
