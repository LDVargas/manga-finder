# Parsing y Normalización — Manga Finder

Documentación del pipeline de procesamiento del archivo fuente `MIS_MANGAS_RESCATADOS.txt`.

## Archivo fuente

**Ruta:** `MIS_MANGAS_RESCATADOS.txt` (en la raíz del proyecto)
**Encoding:** UTF-8
**Tamaño:** ~3,779 entradas (3,207 únicas tras deduplicación)

### Formato

```
[2 líneas de header — se ignoran]
FUENTE | ESTADO | CAP | NOMBRE DEL MANGA
...
```

**Ejemplo de líneas:**
```
Web     | Siguiendo | 1057 | ONE PIECE
Firefox | siguiendo | 1057 | one piece - -
Web     | Leyendo   | 23   | Kaguya-sama: Love is War
Firefox | leyendo   | 23   | kaguya-sama: love is war - -
```

### Campos

| Campo | Descripción | Valores posibles |
|---|---|---|
| FUENTE | Origen del registro | `Web`, `Firefox` |
| ESTADO | Estado de lectura | `Siguiendo`, `Leyendo`, `Pendiente`, `Leido` (case-insensitive) |
| CAP | Capítulos leídos | Número decimal (ej: `23`, `23.5`, `1057`) |
| NOMBRE | Título del manga | Cualquier texto, puede contener `\|` escapado |

**Edge cases:**
- Títulos con `|` en el nombre: se manejan con `"|".join(parts[3:])` (todo lo que quede después del 3er separador)
- Capítulos no numéricos: se tratan como `0.0`
- Estado en minúsculas: se normaliza con `.lower()`

### Patrón de duplicados

Cada manga de ZonaTMO aparece **dos veces**:

| Fuente | Características |
|---|---|
| `Web` | Título en MAYÚSCULAS, estado capitalizado, sin sufijo |
| `Firefox` | Título en minúsculas, estado en minúsculas, sufijo ` - -` |

El sufijo ` - -` es un artefacto de cómo Firefox exporta los favoritos (el formato original era `Título - - Descripción`).

## Pipeline de `parser.py`

```
parse(filepath)
  │
  ├─ Abrir con encoding='utf-8', errors='replace'
  ├─ Skipear líneas 0 y 1 (headers)
  │
  └─ Para cada línea:
       ├─ split('|', max 4 partes)
       ├─ source = parts[0].strip()
       ├─ status = parts[1].lower().strip()
       ├─ chapters = float(parts[2]) — default 0.0 si ValueError
       ├─ title_raw = '|'.join(parts[3:]).strip()
       │
       ├─ key = normalize(title_raw)  ← clave de dedup
       │
       ├─ title_display = title_raw.removesuffix("- -").rstrip(" -").strip()
       │
       └─ Si key ya existe en raw{}:
            ├─ Si source == "web" → actualizar title (preferir mayúsculas)
            ├─ Si chapters > existing → actualizar chapters
            └─ Si status más prioritario → actualizar status
          Si key no existe:
            └─ Insertar {title, chapters, status, source}

  └─ Retornar list[MangaEntry] con k=title_normalized, v=datos mergeados
```

### Prioridad de status

```python
_STATUS_PRIORITY = {
    "leido":     4,  # Más prioritario
    "leyendo":   3,
    "siguiendo": 2,
    "pendiente": 1,  # Menos prioritario
}
```

Si el mismo manga aparece como "leyendo" en Web y "pendiente" en Firefox, se conserva "leyendo".

## `normalizer.py` — Función `normalize()`

### Transformaciones aplicadas

```python
normalize("ONE PIECE - -")
  → strip()           → "ONE PIECE - -"
  → remove " - -"     → "ONE PIECE"
  → lower()           → "one piece"
  → NFD decompose     → separar caracteres base de diacríticos
  → remove Mn chars   → eliminar diacríticos: "café" → "cafe"
  → replace [^\w\s]   → reemplazar puntuación con espacios
  → collapse spaces   → un solo espacio entre palabras
  → strip()           → "one piece"
```

### Ejemplos

| Input | Output |
|---|---|
| `"ONE PIECE - -"` | `"one piece"` |
| `"Kaguya-sama: Love is War"` | `"kaguya sama love is war"` |
| `"Café au lait!!"` | `"cafe au lait"` |
| `"Naruto (2022)"` | `"naruto 2022"` |
| `"Re:Zero"` | `"re zero"` |

### Uso en fuzzy matching

Cuando se busca en MangaDex, la query también se normaliza implícitamente. `rapidfuzz.fuzz.token_set_ratio` ya maneja bien la comparación ignorando orden de palabras, por lo que la normalización aquí sirve principalmente para deduplicación.

### Casos no cubiertos

- Títulos con números romanos: `"Dragon Ball Z"` vs `"Dragon Ball Z"` — funciona
- Títulos muy cortos (1–2 chars): riesgo de falsos positivos en fuzzy matching
- Títulos en japonés sin transliteración: MangaDex los lista también en `altTitles` → se comparan correctamente en `_best_title_score()`

## Resultado en base de datos

Tras el parseo e inserción:

```sql
SELECT title, title_normalized, chapters_read, status
FROM mangas
ORDER BY title
LIMIT 5;
```

```
title                          | title_normalized              | chapters_read | status
-------------------------------+-------------------------------+---------------+----------
1/2 Prince                     | 1 2 prince                    | 75.0          | leido
100 Days with Mr. Arrogant     | 100 days with mr arrogant     | 12.0          | pendiente
...
```

La columna `title_normalized` tiene constraint `UNIQUE` — es la clave de idempotencia.

## Actualizaciones del archivo fuente

Si `MIS_MANGAS_RESCATADOS.txt` se actualiza con nuevas entradas, reiniciar el servidor es suficiente — el startup ejecuta `bulk_insert_mangas()` con `ON CONFLICT DO NOTHING`, insertando solo las novedades sin afectar los resultados ya guardados.
