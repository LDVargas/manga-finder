import json
import os
import asyncpg
from manga_finder.parser import MangaEntry


_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=2, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mangas (
                id                    SERIAL PRIMARY KEY,
                title                 TEXT NOT NULL,
                title_normalized      TEXT NOT NULL UNIQUE,
                chapters_read         NUMERIC(8,1) DEFAULT 0,
                status                TEXT,
                mangadex_id           TEXT,
                mangadex_url          TEXT,
                match_score           NUMERIC(5,2),
                available_languages   JSONB,
                chapters_available_es INTEGER,
                chapters_available_en INTEGER,
                chapters_ok           BOOLEAN,
                search_status         TEXT DEFAULT 'pending'
            )
        """)


async def bulk_insert_mangas(entries: list[MangaEntry]) -> int:
    """Insert new manga entries, skip existing ones. Returns count of inserted rows."""
    pool = await get_pool()
    inserted = 0
    async with pool.acquire() as conn:
        for e in entries:
            result = await conn.execute(
                """
                INSERT INTO mangas (title, title_normalized, chapters_read, status)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (title_normalized) DO NOTHING
                """,
                e.title, e.title_normalized, e.chapters_read, e.status,
            )
            if result == "INSERT 0 1":
                inserted += 1
    return inserted


async def get_all(
    search_status: str | None = None,
    reading_status: str | None = None,
    language: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    pool = await get_pool()
    conditions = []
    params: list = []
    idx = 1

    if search_status:
        conditions.append(f"search_status = ${idx}")
        params.append(search_status)
        idx += 1
    if reading_status:
        conditions.append(f"status = ${idx}")
        params.append(reading_status)
        idx += 1
    if language:
        conditions.append(f"available_languages @> ${idx}::jsonb")
        params.append(json.dumps([language]))
        idx += 1
    if query:
        conditions.append(f"LOWER(title) LIKE ${idx}")
        params.append(f"%{query.lower()}%")
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM mangas {where}", *params)
        rows = await conn.fetch(
            f"""
            SELECT id, title, chapters_read, status, mangadex_id, mangadex_url,
                   match_score, available_languages, chapters_available_es,
                   chapters_available_en, chapters_ok, search_status
            FROM mangas {where}
            ORDER BY title
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params, limit, offset,
        )

    return [dict(r) for r in rows], total


async def get_pending(limit: int = 500) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title, title_normalized, chapters_read
            FROM mangas
            WHERE search_status = 'pending'
            ORDER BY id
            LIMIT $1
            """,
            limit,
        )
    return [dict(r) for r in rows]


async def update_result(
    manga_id: int,
    mangadex_id: str | None,
    mangadex_url: str | None,
    match_score: float | None,
    available_languages: list[str] | None,
    chapters_available_es: int | None,
    chapters_available_en: int | None,
    chapters_ok: bool | None,
    search_status: str,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE mangas SET
                mangadex_id           = $1,
                mangadex_url          = $2,
                match_score           = $3,
                available_languages   = $4,
                chapters_available_es = $5,
                chapters_available_en = $6,
                chapters_ok           = $7,
                search_status         = $8
            WHERE id = $9
            """,
            mangadex_id,
            mangadex_url,
            match_score,
            json.dumps(available_languages) if available_languages is not None else None,
            chapters_available_es,
            chapters_available_en,
            chapters_ok,
            search_status,
            manga_id,
        )


async def reset_manga(manga_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE mangas SET
                mangadex_id=NULL, mangadex_url=NULL, match_score=NULL,
                available_languages=NULL, chapters_available_es=NULL,
                chapters_available_en=NULL, chapters_ok=NULL,
                search_status='pending'
            WHERE id=$1
            """,
            manga_id,
        )


async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM mangas")
        found = await conn.fetchval("SELECT COUNT(*) FROM mangas WHERE search_status='found'")
        not_found = await conn.fetchval("SELECT COUNT(*) FROM mangas WHERE search_status='not_found'")
        error = await conn.fetchval("SELECT COUNT(*) FROM mangas WHERE search_status='error'")
        pending = await conn.fetchval("SELECT COUNT(*) FROM mangas WHERE search_status='pending'")
        chapters_ok = await conn.fetchval("SELECT COUNT(*) FROM mangas WHERE chapters_ok=TRUE")
    return {
        "total": total,
        "found": found,
        "not_found": not_found,
        "error": error,
        "pending": pending,
        "chapters_ok": chapters_ok,
    }
