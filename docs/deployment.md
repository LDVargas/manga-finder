# Deployment — Manga Finder

> Esta es una herramienta local personal. No está diseñada para despliegue en producción remota. Esta guía cubre el entorno local en Windows.

## Entorno actual

- **OS:** Windows 11
- **Shell:** PowerShell
- **Python:** 3.13
- **PostgreSQL:** Local, localhost:5432
- **Servidor:** uvicorn en modo desarrollo (sin workers múltiples)

## Iniciar

```powershell
cd d:\Proyectos\WebScrapperManga
python main.py
```

La aplicación queda disponible en: http://localhost:8000

### Lo que hace el startup

1. Carga `.env` → `DATABASE_URL`
2. `init_db()` → crea tabla `mangas` si no existe (idempotente)
3. `parse(MIS_MANGAS_RESCATADOS.txt)` → 3,207 entradas únicas
4. `bulk_insert_mangas()` → inserta solo las nuevas (ON CONFLICT DO NOTHING)
5. Imprime cuántas se insertaron (0 si ya estaban todas)

### Comportamiento en reinicios

- Los datos en PostgreSQL **persisten** entre reinicios
- El estado `_search_progress` (progreso de búsqueda) **se pierde** al reiniciar — es en memoria
- Las búsquedas interrumpidas se pueden **reanudar** con "Buscar Todo" (procesa solo `pending`)

## Detener

```powershell
Ctrl+C
```

uvicorn maneja `SIGINT` limpiamente: cierra el pool de asyncpg (`close_pool()` en lifespan shutdown).

## Requisitos del entorno

### PostgreSQL

La base de datos debe estar corriendo y accesible. Verificar:

```sql
-- En psql o pgAdmin:
SELECT version();  -- Confirmar conectividad

-- Crear DB si no existe:
CREATE DATABASE "MangaList";

-- Verificar permisos:
\c MangaList
SELECT current_user;
```

### Variables de entorno

El archivo `.env` debe estar en `d:\Proyectos\WebScrapperManga\.env`:

```env
DATABASE_URL=postgresql://postgres:admin@localhost:5432/MangaList
```

Si `DATABASE_URL` no está configurado, el servidor falla al inicio con `KeyError: 'DATABASE_URL'`.

### Acceso a internet

Requerido para la búsqueda en MangaDex. Sin acceso:
- El servidor inicia correctamente
- La búsqueda masiva fallará (timeouts/errores de red marcados como `error` en DB)

## Puerto y binding

El servidor corre en `127.0.0.1:8000` (solo localhost). No es accesible desde otras máquinas de la red.

Para cambiar el puerto (si 8000 está ocupado):

```python
# main.py — última línea
uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=False)
```

## Consideraciones de rendimiento

| Operación | Tiempo estimado |
|---|---|
| Startup | < 5 segundos |
| Carga inicial de 3,207 mangas en UI | < 1 segundo |
| Búsqueda masiva completa (3,207 mangas) | 8–15 minutos |
| Búsqueda individual (un manga) | 3–8 segundos |
| Exportar CSV | < 2 segundos |

El cuello de botella es el rate limit de MangaDex (4 req/s). El código está optimizado para este límite.

## Pool de conexiones PostgreSQL

```python
# database.py
_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
```

- **min_size=2:** 2 conexiones siempre abiertas
- **max_size=10:** máximo 10 conexiones concurrentes

Para esta escala (3,207 mangas, uso local) el default es más que suficiente.

## Solución a problemas comunes

### Puerto 8000 ocupado

```powershell
# Encontrar qué proceso usa el puerto
netstat -ano | findstr :8000
# Matar el proceso (PID)
taskkill /PID <pid> /F
```

### PostgreSQL no conecta

```powershell
# Verificar servicio
Get-Service postgresql*
# Iniciar si está detenido
Start-Service postgresql-x64-17  # ajustar versión
```

### La búsqueda masiva se colgó

Verificar en la UI: si `_search_progress.running` es `true` pero `done` no avanza:
1. Revisar logs del servidor en la consola
2. Revisar si hay errores de red o de MangaDex
3. Si es necesario, reiniciar el servidor — la búsqueda se puede reanudar

### Carácteres incorrectos en consola

Normal en Windows — la consola no puede mostrar caracteres UTF-8 como `Í` o `ñ`. Los datos en DB y browser son correctos.
