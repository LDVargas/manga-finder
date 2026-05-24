# Roadmap — Manga Finder

## Estado actual ✅

- [x] Parseo y deduplicación de `MIS_MANGAS_RESCATADOS.txt` (3,207 mangas únicos)
- [x] Inserción idempotente en PostgreSQL
- [x] Búsqueda masiva en MangaDex con fuzzy matching (rapidfuzz)
- [x] Verificación de capítulos disponibles (ES/EN)
- [x] UI web con filtros, paginación, progreso en tiempo real
- [x] Exportación CSV
- [x] Re-búsqueda individual por manga
- [x] Rate limiting y retry con backoff exponencial

## Fase 1 — Multi-site: Provider Pattern (PLANIFICADA)

**Prerequisito para Fases 2 y 3. No cambia comportamiento observable.**

### Objetivo

Refactorizar `mangadex.py` para introducir una abstracción `SearchProvider` que permita agregar nuevos sitios sin modificar la lógica de orquestación.

### Cambios

**Nuevos archivos:**
```
manga_finder/providers/
  __init__.py
  base.py        ← SiteResult dataclass + SearchProvider Protocol
  mangadex.py    ← lógica actual de mangadex.py (refactorizada a clase)
```

**`providers/base.py`:**
```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class SiteResult:
    site: str                      # "mangadex" | "inmanga" | "comick"
    url: str
    score: float
    chapters_es: int
    chapters_en: int
    available_languages: list[str]

class SearchProvider(Protocol):
    name: str
    async def search(self, title: str, title_normalized: str) -> "SiteResult | None": ...
```

**Cambios en `mangadex.py`:**
- Mantener función `search_and_update()` como wrapper
- Delegar a `providers/mangadex.py` internamente

**Cambios en `router.py`:**
- `_run_full_search()` recibe `list[SearchProvider]`
- Para cada manga: lanzar todos los providers en paralelo con `asyncio.gather`

### DB

```sql
ALTER TABLE mangas ADD COLUMN IF NOT EXISTS site_results JSONB DEFAULT '[]';
-- [{site, url, score, chapters_es, chapters_en, available_languages}, ...]
```

Las columnas actuales (`mangadex_url`, `match_score`, etc.) se mantienen con los datos del **mejor resultado** (mayor score) para compatibilidad con los filtros existentes.

---

## Fase 2 — InManga Provider (PLANIFICADA)

**Fuente de español con mayor cobertura de fan-traducciones que MangaDex.**

### Viabilidad

- API no oficial pero funcional
- Comunidad de scrapers Python existente
- Posible Cloudflare — puede requerir `cloudscraper`
- Dificultad: **Media**

### Endpoints a usar

```
Búsqueda:
POST https://inmanga.com/manga/getMangasConsultResult
Body: { "filter": "título del manga" }
Response: JSON con lista { Identification, Name, ... }

Capítulos:
GET https://inmanga.com/chapter/getall/{manga_uuid}
Response: JSON con lista de capítulos y su idioma
```

### Nuevo archivo

`manga_finder/providers/inmanga.py` — clase `InMangaProvider` implementando `SearchProvider`.

### Dependencias nuevas

```
cloudscraper>=1.2.71    # bypass Cloudflare (si necesario)
beautifulsoup4>=4.12.0  # parsing HTML fallback
```

---

## Fase 3 — ComicK Provider (PLANIFICADA)

**Mejor cobertura de manhwa y manhua, especialmente series coreanas que no están en MangaDex.**

### Viabilidad

- API no oficial pero documentada por comunidad
- Cloudflare activo — requiere `cloudscraper`
- Dificultad: **Media-Alta**

### Endpoints a usar

```
Búsqueda:
GET https://api.comick.fun/v1.0/search?q={titulo}&limit=10
Response: JSON con { hid, title, slug, ... }

Capítulos ES:
GET https://api.comick.fun/comic/{hid}/chapters?lang=es&limit=99999

Capítulos EN:
GET https://api.comick.fun/comic/{hid}/chapters?lang=en&limit=99999

URL de lectura: https://comick.io/comic/{slug}
```

### Nuevo archivo

`manga_finder/providers/comick.py` — clase `ComicKProvider` implementando `SearchProvider`.

---

## Fase 4 — UI Multi-sitio (PLANIFICADA)

**Depende de Fases 1 + al menos una de Fase 2 o 3.**

### Cambios en la UI

- Reemplazar columna "URL MangaDex" → columna "Leer en" con múltiples links
- Badges de color por fuente:
  - 🟣 MangaDex (`#7c3aed`)
  - 🟢 InManga (`#059669`)
  - 🔵 ComicK (`#2563eb`)
- Nuevo filtro "Disponible en" (dropdown: todos / MangaDex / InManga / ComicK)
- `chapters_ok` = `true` si **cualquier** sitio tiene capítulos suficientes
- Cap. ES y Cap. EN muestran el **máximo** entre todos los sitios

### Cambios en API

- `/api/mangas` incluye `site_results` en cada item:
```json
{
  "site_results": [
    {"site": "mangadex", "url": "https://...", "score": 95.0, "chapters_es": 200, "chapters_en": 210},
    {"site": "inmanga",  "url": "https://...", "score": 88.0, "chapters_es": 185, "chapters_en": 0}
  ]
}
```

---

## Mejoras técnicas (backlog sin prioridad definida)

### Logging estructurado

Reemplazar `print()` y `except Exception: pass` por `logging` con nivel configurable.

```python
import logging
logger = logging.getLogger(__name__)
logger.error("Error buscando manga %d: %s", manga_id, exc)
```

### Persistencia del estado de búsqueda

`_search_progress` en memoria se pierde al reiniciar. Alternativa: tabla `search_sessions` en PostgreSQL con estado de la sesión actual.

### Tests

Suite mínima con `pytest` y `pytest-asyncio`:
- `test_parser.py` — casos de deduplicación con datos de ejemplo
- `test_normalizer.py` — tabla de transformaciones esperadas
- `test_mangadex.py` — mock de `httpx` para testear scoring sin llamadas reales

### Fix DT-1

```python
# database.py — alinear default con uso real
async def get_pending(limit: int = 10000) -> list[dict]:
```

### Paginación en búsqueda masiva

Actualmente `get_pending(limit=10000)` carga todo en memoria. Para listas más grandes, procesar con `OFFSET` paginado.

---

## Sitios descartados

Los siguientes sitios fueron investigados y descartados por alta dificultad sin beneficio suficiente:

| Sitio | Razón del descarte |
|---|---|
| bokugents.com | Sin API, catálogo nicho, solo browse |
| mangasnosekai.com | Bloqueo activo (403), sin API |
| manhwaweb.com | Bloqueo activo (403), sin API |
| Webtoons | Sin API pública, catálogo distinto (webtoons oficiales) |

---

## Orden de implementación recomendado

1. Terminar búsqueda masiva en MangaDex (ya en curso)
2. Analizar CSV de resultados → cuántos `not_found`, qué tipo de contenido
3. Implementar Fase 1 (provider pattern) — sin cambio de comportamiento
4. Implementar Fase 2 (InManga) — re-buscar los `not_found`
5. Implementar Fase 4 (UI) — mostrar múltiples fuentes
6. Evaluar si Fase 3 (ComicK) aporta valor adicional

> **Nota de performance:** Con búsqueda paralela en todos los providers, el tiempo total NO se multiplica. Cada provider tiene su propio `Semaphore(4)`. El tiempo estimado sigue siendo ~10–15 min para 3,207 mangas.
