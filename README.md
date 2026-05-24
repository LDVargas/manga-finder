# Manga Finder

Herramienta local para encontrar dónde continuar leyendo una lista personal de mangas. Busca en MangaDex usando fuzzy matching, verifica disponibilidad de capítulos en español e inglés, y presenta los resultados en una interfaz web filtrable con exportación CSV.

> Originalmente creada para recuperar listas exportadas de ZonaTMO (TuMangaOnline, sitio cerrado en 2023).

## ¿Qué hace?

1. Lee tu lista de mangas desde un archivo de texto con formato delimitado por pipes
2. Busca cada manga en la API pública de MangaDex usando fuzzy matching de títulos
3. Verifica que los capítulos leídos estén disponibles en ES o EN
4. Presenta los resultados en una interfaz web con filtros, paginación y exportación CSV

## Stack

| Componente | Tecnología |
|---|---|
| Backend | FastAPI 0.115.5 + uvicorn |
| Base de datos | PostgreSQL (asyncpg) |
| HTTP client | httpx (async) |
| Fuzzy matching | rapidfuzz |
| Templates | Jinja2 |
| Frontend | HTML + Vanilla JS |

## Requisitos

- Python 3.10+
- PostgreSQL accesible en localhost

## Archivo de entrada

La aplicación lee una lista de mangas desde un archivo de texto. **Este archivo es privado y no está incluido en el repositorio** — debes proveer el tuyo.

### Formato esperado

El archivo usa separador `|` con 4 columnas. Las dos primeras líneas son encabezado:

```
FUENTE             | ESTADO       |    CAP | NOMBRE DEL MANGA
----------------------------------------------------------------------------------------------------
Web                | leyendo      |   15.0 | Berserk
Web                | siguiendo    |    0.0 | Vinland Saga
Web                | leido        |  120.0 | Fullmetal Alchemist
Web                | pendiente    |    0.0 | One Piece
```

| Columna | Valores válidos | Descripción |
|---|---|---|
| `FUENTE` | `Web`, `Firefox`, cualquier string | Fuente de la exportación (afecta deduplicación de títulos duplicados) |
| `ESTADO` | `leyendo`, `siguiendo`, `pendiente`, `leido` | Estado de lectura personal |
| `CAP` | Número decimal (ej. `42.0`) | Capítulo hasta el que se leyó |
| `NOMBRE DEL MANGA` | Texto libre | Título del manga |

La aplicación deduplica entradas con el mismo título normalizado, fusionando los capítulos y priorizando el estado más relevante (`leido > leyendo > siguiendo > pendiente`).

### Nombre del archivo

Por defecto se llama `MIS_MANGAS_RESCATADOS.txt` y debe estar en la raíz del proyecto. Puedes cambiarlo con la variable de entorno `MANGA_LIST_PATH` en tu `.env`.

## Instalación

```bash
git clone <url-del-repo>
cd WebScrapperManga
pip install -r requirements.txt
```

## Configuración

```bash
cp .env.example .env
# Editar .env con tus credenciales de PostgreSQL
```

La base de datos y la tabla `mangas` se crean automáticamente al iniciar. No se requiere migración manual.

Crear la base de datos en PostgreSQL (solo la primera vez):

```sql
CREATE DATABASE "MangaList";
```

## Ejecución

```bash
python main.py
```

La aplicación estará disponible en [http://localhost:8000](http://localhost:8000).

Al iniciar, el servidor:
1. Conecta a PostgreSQL y crea la tabla `mangas` si no existe
2. Parsea el archivo de entrada e inserta los mangas únicos (operación idempotente)
3. Queda en espera hasta que el usuario inicie la búsqueda

## Uso

1. Abrir [http://localhost:8000](http://localhost:8000)
2. Hacer clic en **"Buscar Todo"** para iniciar la búsqueda masiva en MangaDex
   - Duración estimada: 8–15 minutos para ~3,000 mangas (rate limit 4 req/s)
   - La búsqueda persiste en DB; si se interrumpe, solo procesa los `pending`
3. Filtrar resultados por estado de búsqueda, estado de lectura o idioma
4. Hacer clic en **"Abrir ↗"** para ir al manga en MangaDex
5. Usar **"↺"** para re-buscar un manga individual
6. Exportar a CSV con el botón **"Exportar CSV"**

## Estructura del proyecto

```
WebScrapperManga/
├── main.py                         # Entry point — FastAPI + lifespan
├── requirements.txt
├── .env.example                    # Plantilla de variables de entorno
├── .env                            # ← NO incluido en repo (credenciales)
├── MIS_MANGAS_RESCATADOS.txt       # ← NO incluido en repo (datos personales)
├── manga_finder/
│   ├── __init__.py
│   ├── normalizer.py   # Normalización de títulos (acentos, casing, puntuación)
│   ├── parser.py       # Parseo y deduplicación del archivo de entrada
│   ├── database.py     # Pool asyncpg + CRUD PostgreSQL
│   ├── mangadex.py     # Cliente API MangaDex + fuzzy matching + orquestación
│   └── router.py       # Rutas FastAPI (REST + HTML)
├── templates/
│   └── index.html      # UI: tabla filtrable con progreso y paginación
└── docs/               # Documentación técnica
```

## Variables de entorno

| Variable | Requerida | Descripción | Ejemplo |
|---|---|---|---|
| `DATABASE_URL` | Sí | Cadena de conexión PostgreSQL | `postgresql://user:pass@localhost:5432/MangaList` |
| `MANGA_LIST_PATH` | No | Ruta al archivo de mangas | `mi_lista.txt` (default: `MIS_MANGAS_RESCATADOS.txt`) |

## Schema de base de datos

Tabla `mangas`:

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL PK | Identificador interno |
| `title` | TEXT | Título de display |
| `title_normalized` | TEXT UNIQUE | Título normalizado (clave de dedup) |
| `chapters_read` | NUMERIC(8,1) | Capítulos leídos en el archivo de entrada |
| `status` | TEXT | Estado de lectura: `leyendo`, `siguiendo`, `pendiente`, `leido` |
| `mangadex_id` | TEXT | UUID del manga en MangaDex |
| `mangadex_url` | TEXT | URL directa de lectura |
| `match_score` | NUMERIC(5,2) | Score de matching fuzzy (0–100) |
| `available_languages` | JSONB | Array de idiomas disponibles: `["es", "en"]` |
| `chapters_available_es` | INTEGER | Capítulos disponibles en español |
| `chapters_available_en` | INTEGER | Capítulos disponibles en inglés |
| `chapters_ok` | BOOLEAN | `True` si capítulos disponibles >= capítulos leídos |
| `search_status` | TEXT | `pending`, `found`, `not_found`, `error` |

## Troubleshooting

**El servidor no inicia:**
- Verificar que PostgreSQL esté corriendo
- Verificar credenciales en `.env`
- Verificar que la base de datos exista: `CREATE DATABASE "MangaList";`

**El archivo de mangas no se encuentra:**
- Verificar que el archivo esté en la raíz del proyecto con el nombre correcto
- O configurar `MANGA_LIST_PATH` en `.env` con la ruta a tu archivo

**La búsqueda se interrumpió:**
- Hacer clic en "Buscar Todo" nuevamente — solo procesa los `pending`

**Muchos mangas con score bajo:**
- El umbral mínimo es 72%. Títulos muy cortos o con caracteres especiales pueden no encontrarse
- Usar "↺" para re-buscar individualmente y revisar manualmente si es necesario

**Caracteres extraños en la consola de Windows:**
- No es un error — la consola de Windows (cp850) no muestra acentos correctamente
- Los datos en la DB y en el browser son correctos (UTF-8)

## Roadmap

Ver [docs/roadmap.md](docs/roadmap.md) para el plan de expansión con soporte multi-sitio (InManga, ComicK).

## Licencia

[MIT](LICENSE)
