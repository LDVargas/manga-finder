# Guía de Desarrollo — Manga Finder

## Setup inicial

### Requisitos

- Python 3.10+ (el proyecto usa 3.13)
- PostgreSQL con base de datos `MangaList` accesible
- Acceso a internet (para la API de MangaDex)

### Instalación

```bash
cd d:\Proyectos\WebScrapperManga

# Instalar dependencias
pip install -r requirements.txt

# Crear .env
echo DATABASE_URL=postgresql://postgres:admin@localhost:5432/MangaList > .env
```

### Verificar conexión a PostgreSQL

```bash
# En psql o pgAdmin, crear la DB si no existe:
CREATE DATABASE "MangaList";
```

### Iniciar el servidor

```bash
python main.py
# → http://localhost:8000
```

El servidor es **idempotente al iniciar** — ejecutar varias veces no duplica datos.

## Flujo de trabajo recomendado

### Para modificar lógica de búsqueda (`mangadex.py`)

1. Verificar que el servidor NO esté en medio de una búsqueda masiva (esperar o interrumpir)
2. Modificar el archivo
3. Reiniciar el servidor: `Ctrl+C` → `python main.py`
4. Usar el botón "↺" para probar con un manga individual
5. Verificar en la UI que los datos sean correctos

### Para modificar el frontend (`templates/index.html`)

Los templates de Jinja2 se re-leen en cada request (en modo sin `reload=True`). Sin embargo, uvicorn **sin** `reload=True` lee los templates desde disco en cada `TemplateResponse` — no requiere reinicio para cambios en HTML/CSS/JS.

**Excepción:** Si se cambian rutas o lógica en `router.py`, sí se necesita reinicio.

### Para modificar el schema de base de datos

1. Agregar migraciones como `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`
2. Integrar la migración en `init_db()` en `database.py`
3. `CREATE TABLE IF NOT EXISTS` ya maneja la creación inicial
4. **NUNCA** hacer `DROP TABLE` ni `DELETE FROM mangas` sin confirmar con el usuario

### Para agregar un nuevo endpoint

1. Agregar función en `router.py` con decorador `@router.get/post/...`
2. Si necesita datos de DB, agregar función en `database.py`
3. Si necesita llamar a MangaDex, agregar en `mangadex.py`
4. Reiniciar servidor para aplicar cambios

## Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `DATABASE_URL` | Sí | — | Cadena de conexión PostgreSQL |

El código usa `os.environ["DATABASE_URL"]` (falla explícitamente si falta).

## Debugging

### Ver estado de la DB

```sql
-- Conteo por estado de búsqueda
SELECT search_status, COUNT(*) FROM mangas GROUP BY search_status;

-- Mangas con error
SELECT title, search_status FROM mangas WHERE search_status = 'error';

-- Mangas no encontrados con score más alto (posibles falsos negativos)
SELECT title, match_score FROM mangas
WHERE search_status = 'not_found'
ORDER BY match_score DESC NULLS LAST
LIMIT 20;
```

### Probar búsqueda MangaDex manualmente

```python
# En una shell Python con el servidor corriendo:
import asyncio
from manga_finder import mangadex

asyncio.run(mangadex.search_and_update(1, "One Piece", "one piece", 1057.0))
```

### Logs del servidor

Los logs van a stdout de uvicorn. Agregar `print()` temporales es aceptable para debugging.

## Convenciones

### Python

- **Type hints** en todas las funciones públicas
- **Async** para todo I/O (DB, HTTP)
- **No clases** donde funciones libres son suficientes
- **SQL parametrizado** — nunca concatenar strings en queries
- **`asyncpg.Record`** se convierte a `dict` con `dict(r)` antes de retornar

### Commits

No hay gitignore de mensajes. Usar descripción clara de qué y por qué.

### Tests

No hay tests en este proyecto. Para cambios críticos en lógica de matching:
1. Probar manualmente con 5–10 mangas conocidos
2. Verificar en la UI que los resultados sean correctos
3. Exportar CSV antes y comparar scores

## Problemas conocidos y deuda técnica

### Activos

| ID | Problema | Severidad | Ubicación |
|---|---|---|---|
| DT-1 | `get_pending(limit=500)` en firma pero router llama con `limit=10000` | Baja | `database.py:114`, `router.py:141` |
| DT-2 | `_search_progress` en memoria — se pierde al reiniciar | Media | `router.py:15` |
| DT-3 | `_search_task` declarado pero nunca asignado ni cancelado | Baja | `router.py:14` |
| DT-4 | Sin logging estructurado — errores de búsqueda se silencian silenciosamente | Media | `router.py:159-166` |
| DT-5 | Sin tests | Alta | Todo el proyecto |

### DT-1: `get_pending` limit inconsistente

```python
# database.py — la firma sugiere 500 como max
async def get_pending(limit: int = 500) -> list[dict]:

# router.py — se pasa 10000 (ignora el default de la firma)
pending = await database.get_pending(limit=10000)
```

**Impacto:** Ninguno en la práctica (funciona correctamente). La firma es engañosa.

**Fix simple:** Cambiar `limit: int = 500` a `limit: int = 10000` en `database.py`.

### DT-2: Estado de búsqueda en memoria

Si el servidor se reinicia durante una búsqueda masiva:
- Los datos en la DB están correctos (parcialmente procesados)
- La UI muestra "Iniciando..." en lugar del progreso real

**Workaround actual:** Reiniciar la búsqueda con "Buscar Todo" — solo procesa los `pending`.

**Fix potencial:** Persistir `_search_progress` en una tabla auxiliar de PostgreSQL.

## Agregar dependencias

```bash
# Instalar y actualizar requirements.txt
pip install nueva-libreria==x.y.z
# Agregar manualmente a requirements.txt con versión exacta
```

**Dependencias futuras planificadas:**
- `cloudscraper` — para bypass de Cloudflare en InManga y ComicK
- `beautifulsoup4` — para parsing HTML si InManga no retorna JSON limpio

Ver [roadmap.md](roadmap.md) para contexto.
