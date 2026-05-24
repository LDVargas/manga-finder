import asyncio
import csv
import io
import json
from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from manga_finder import database, mangadex

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# Search task state
_search_task: asyncio.Task | None = None
_search_progress: dict = {"running": False, "total": 0, "done": 0, "found": 0, "not_found": 0, "errors": 0}


@router.get("/")
async def index(request: Request):
    stats = await database.get_stats()
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats})


@router.get("/api/mangas")
async def list_mangas(
    search_status: str | None = Query(None),
    reading_status: str | None = Query(None),
    language: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows, total = await database.get_all(
        search_status=search_status,
        reading_status=reading_status,
        language=language,
        query=q,
        limit=limit,
        offset=offset,
    )
    # Deserialize available_languages from JSON string if needed
    for row in rows:
        if isinstance(row.get("available_languages"), str):
            try:
                row["available_languages"] = json.loads(row["available_languages"])
            except Exception:
                row["available_languages"] = []
        # Convert Decimal to float for JSON serialization
        for field in ("chapters_read", "match_score"):
            if row.get(field) is not None:
                row[field] = float(row[field])
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/api/stats")
async def stats():
    return await database.get_stats()


@router.get("/api/search/progress")
async def search_progress():
    return _search_progress


@router.post("/api/search/start")
async def start_search(background_tasks: BackgroundTasks):
    global _search_task
    if _search_progress["running"]:
        return {"status": "already_running"}
    background_tasks.add_task(_run_full_search)
    return {"status": "started"}


@router.post("/api/search/{manga_id}/retry")
async def retry_manga(manga_id: int, background_tasks: BackgroundTasks):
    await database.reset_manga(manga_id)
    background_tasks.add_task(_search_single, manga_id)
    return {"status": "queued"}


@router.get("/api/export/csv")
async def export_csv():
    rows, _ = await database.get_all(limit=100000, offset=0)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "title", "chapters_read", "status", "mangadex_url",
                    "available_languages", "chapters_available_es", "chapters_available_en",
                    "chapters_ok", "match_score", "search_status"],
    )
    writer.writeheader()
    for row in rows:
        langs = row.get("available_languages")
        if isinstance(langs, list):
            row["available_languages"] = ",".join(langs)
        elif isinstance(langs, str):
            try:
                row["available_languages"] = ",".join(json.loads(langs))
            except Exception:
                pass
        for field in ("chapters_read", "match_score"):
            if row.get(field) is not None:
                row[field] = float(row[field])
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=manga_results.csv"},
    )


async def _search_single(manga_id: int) -> None:
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, title, title_normalized, chapters_read FROM mangas WHERE id=$1", manga_id
        )
    if row:
        try:
            await mangadex.search_and_update(
                row["id"], row["title"], row["title_normalized"], float(row["chapters_read"])
            )
        except Exception:
            await database.update_result(
                manga_id=row["id"], mangadex_id=None, mangadex_url=None,
                match_score=None, available_languages=None,
                chapters_available_es=None, chapters_available_en=None,
                chapters_ok=None, search_status="error",
            )


async def _run_full_search() -> None:
    global _search_progress
    _search_progress["running"] = True
    _search_progress["done"] = 0
    _search_progress["found"] = 0
    _search_progress["not_found"] = 0
    _search_progress["errors"] = 0

    pending = await database.get_pending(limit=10000)
    _search_progress["total"] = len(pending)

    async def process(row: dict) -> None:
        try:
            await mangadex.search_and_update(
                row["id"], row["title"], row["title_normalized"], float(row["chapters_read"])
            )
            # Re-fetch to check outcome
            pool = await database.get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT search_status FROM mangas WHERE id=$1", row["id"]
                )
            if result == "found":
                _search_progress["found"] += 1
            else:
                _search_progress["not_found"] += 1
        except Exception:
            await database.update_result(
                manga_id=row["id"], mangadex_id=None, mangadex_url=None,
                match_score=None, available_languages=None,
                chapters_available_es=None, chapters_available_en=None,
                chapters_ok=None, search_status="error",
            )
            _search_progress["errors"] += 1
        finally:
            _search_progress["done"] += 1

    # Process in batches to avoid overwhelming memory
    batch_size = 50
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        await asyncio.gather(*[process(row) for row in batch])

    _search_progress["running"] = False
