import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from manga_finder import database
from manga_finder.parser import parse
from manga_finder.router import router

MANGA_LIST = Path(os.getenv("MANGA_LIST_PATH", "MIS_MANGAS_RESCATADOS.txt"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init_db()
    entries = parse(MANGA_LIST)
    inserted = await database.bulk_insert_mangas(entries)
    if inserted > 0:
        print(f"[startup] Inserted {inserted} new manga entries into DB.")
    else:
        print(f"[startup] DB already populated ({len(entries)} unique entries parsed).")
    yield
    await database.close_pool()


app = FastAPI(title="Manga Finder", lifespan=lifespan)
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
