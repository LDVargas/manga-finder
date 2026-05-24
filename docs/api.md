# API Reference — Manga Finder

Base URL: `http://localhost:8000`

## HTML

### `GET /`

Renderiza la interfaz principal.

**Response:** HTML — `templates/index.html` con stats iniciales pre-renderizadas.

---

## REST API

### `GET /api/mangas`

Lista paginada de mangas con filtros opcionales.

**Query parameters:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `q` | string | Búsqueda por título (LIKE, case-insensitive) |
| `search_status` | string | `pending` \| `found` \| `not_found` \| `error` |
| `reading_status` | string | `leyendo` \| `siguiendo` \| `pendiente` \| `leido` |
| `language` | string | `es` \| `en` — filtra mangas con ese idioma disponible |
| `limit` | int | Resultados por página. Default: 50. Rango: 1–500 |
| `offset` | int | Desplazamiento para paginación. Default: 0 |

**Response `200 OK`:**
```json
{
  "items": [
    {
      "id": 1,
      "title": "One Piece",
      "chapters_read": 1057.0,
      "status": "siguiendo",
      "mangadex_id": "32d76d19-8a05-4db0-9fc2-e0b0648fe9d0",
      "mangadex_url": "https://mangadex.org/title/32d76d19...",
      "match_score": 100.0,
      "available_languages": ["es", "en"],
      "chapters_available_es": 1057,
      "chapters_available_en": 1057,
      "chapters_ok": true,
      "search_status": "found"
    }
  ],
  "total": 3207,
  "limit": 50,
  "offset": 0
}
```

**Notas:**
- `chapters_read` y `match_score` son `float` (convertidos desde NUMERIC de PostgreSQL)
- `available_languages` es `list[str]` (deserializado desde JSONB)
- `mangadex_url` y `mangadex_id` son `null` si `search_status != "found"`

---

### `GET /api/stats`

Conteos globales por estado.

**Response `200 OK`:**
```json
{
  "total": 3207,
  "found": 2847,
  "not_found": 312,
  "error": 18,
  "pending": 30,
  "chapters_ok": 2651
}
```

---

### `GET /api/search/progress`

Estado actual de la búsqueda masiva en curso.

**Response `200 OK`:**
```json
{
  "running": true,
  "total": 3207,
  "done": 1452,
  "found": 1301,
  "not_found": 148,
  "errors": 3
}
```

**Notas:**
- Este estado es **en memoria** — se resetea si el servidor se reinicia
- `running: false` con `done: 0` indica que no ha habido búsqueda en esta sesión del servidor
- El estado de cada manga individual persiste en la DB independientemente

---

### `POST /api/search/start`

Inicia la búsqueda masiva en background. Solo procesa mangas con `search_status='pending'`.

**Request:** Sin body.

**Response `200 OK`:**
```json
{ "status": "started" }
```
o si ya hay una búsqueda en curso:
```json
{ "status": "already_running" }
```

**Comportamiento:**
- Crea una `BackgroundTask` de FastAPI (no bloquea la respuesta)
- Procesa en batches de 50 mangas con `asyncio.gather`
- Rate limit: `asyncio.Semaphore(4)` — máximo 4 requests concurrentes a MangaDex
- Actualiza `_search_progress` en tiempo real
- Los errores por manga individual no detienen la búsqueda global

---

### `POST /api/search/{manga_id}/retry`

Resetea y re-busca un manga individual.

**Path params:**
- `manga_id` (int) — ID del manga en la tabla `mangas`

**Response `200 OK`:**
```json
{ "status": "queued" }
```

**Comportamiento:**
- `reset_manga(manga_id)` → `search_status = 'pending'`, borra resultados anteriores
- Lanza `_search_single(manga_id)` como BackgroundTask
- La UI espera 3 segundos y recarga la página actual

---

### `GET /api/export/csv`

Exporta todos los resultados como CSV.

**Response:** `text/csv` con header `Content-Disposition: attachment; filename=manga_results.csv`

**Columnas del CSV:**
```
id, title, chapters_read, status, mangadex_url, available_languages,
chapters_available_es, chapters_available_en, chapters_ok, match_score, search_status
```

**Notas:**
- `available_languages` se serializa como string separado por comas: `"es,en"`
- Incluye TODOS los mangas (limit=100000), no solo los encontrados

---

## Manejo de errores

La API no retorna códigos de error explícitos para errores de negocio — los mangas fallidos se marcan con `search_status='error'` en la DB. Los errores de red o DB sí retornarán `500`.

## Rate limits de MangaDex (referencia)

| Endpoint | Límite |
|---|---|
| `/manga` (búsqueda) | ~5 req/s (respetado con Semaphore(4)) |
| `/manga/{id}/aggregate` | ~5 req/s |

El código implementa retry con backoff exponencial para respuestas 429.
