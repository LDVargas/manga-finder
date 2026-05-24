import asyncio
import math
import httpx
from rapidfuzz import fuzz
from manga_finder import database

MANGADEX_API = "https://api.mangadex.org"
LANGUAGES = ["es", "es-la", "en"]
MIN_SCORE = 72.0

# Global semaphore shared across all search tasks (max 4 concurrent requests)
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(4)
    return _semaphore


def _best_title_score(query: str, manga_data: dict) -> float:
    """Return the highest fuzzy match score between query and all manga titles."""
    candidates: list[str] = []

    # Primary title
    title_obj = manga_data.get("attributes", {}).get("title", {})
    candidates.extend(str(v) for v in title_obj.values() if v)

    # Alt titles
    for alt in manga_data.get("attributes", {}).get("altTitles", []):
        candidates.extend(str(v) for v in alt.values() if v)

    if not candidates:
        return 0.0

    q = query.lower()
    return max(
        max(fuzz.token_set_ratio(q, c.lower()), fuzz.ratio(q, c.lower()))
        for c in candidates
    )


async def _request_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> dict | None:
    delay = 1.0
    for attempt in range(5):
        try:
            resp = await client.get(url, params=params, timeout=20.0)
            if resp.status_code == 429:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if resp.status_code in (500, 502, 503, 504):
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.NetworkError):
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    return None


async def _get_chapter_counts(client: httpx.AsyncClient, manga_id: str) -> tuple[int, int]:
    """Return (chapters_es, chapters_en) count for a manga."""
    sem = get_semaphore()
    counts = {"es": set(), "en": set()}

    for lang_group, langs in [("es", ["es", "es-la"]), ("en", ["en"])]:
        params: dict = {"translatedLanguage[]": langs}
        async with sem:
            data = await _request_with_retry(
                client, f"{MANGADEX_API}/manga/{manga_id}/aggregate", params
            )
        if not data or data.get("result") != "ok":
            continue
        volumes = data.get("volumes", {})
        if not isinstance(volumes, dict):
            continue
        for vol in volumes.values():
            for chap_key in vol.get("chapters", {}).keys():
                try:
                    counts[lang_group].add(float(chap_key))
                except ValueError:
                    pass

    return len(counts["es"]), len(counts["en"])


async def search_and_update(manga_id: int, title: str, title_normalized: str, chapters_read: float) -> None:
    """Search MangaDex for a manga and update the DB with results."""
    sem = get_semaphore()

    async with httpx.AsyncClient(
        headers={"User-Agent": "MangaFinder/1.0 (personal tool)"},
        follow_redirects=True,
    ) as client:
        # Try with normalized title first, then original
        search_queries = [title_normalized, title]
        best_match: dict | None = None
        best_score: float = 0.0

        for query in search_queries:
            params = {
                "title": query,
                "limit": 10,
                "availableTranslatedLanguage[]": LANGUAGES,
                "contentRating[]": ["safe", "suggestive", "erotica", "pornographic"],
            }
            async with sem:
                data = await _request_with_retry(client, f"{MANGADEX_API}/manga", params)

            if not data or not data.get("data"):
                continue

            for result in data["data"]:
                score = _best_title_score(query, result)
                if score > best_score:
                    best_score = score
                    best_match = result

            if best_score >= MIN_SCORE:
                break

        if best_match is None or best_score < MIN_SCORE:
            await database.update_result(
                manga_id=manga_id,
                mangadex_id=None,
                mangadex_url=None,
                match_score=round(best_score, 2),
                available_languages=None,
                chapters_available_es=None,
                chapters_available_en=None,
                chapters_ok=None,
                search_status="not_found",
            )
            return

        mdx_id = best_match["id"]
        mdx_url = f"https://mangadex.org/title/{mdx_id}"

        # Get chapter counts per language
        chap_es, chap_en = await _get_chapter_counts(client, mdx_id)

        available_langs = []
        if chap_es > 0:
            available_langs.append("es")
        if chap_en > 0:
            available_langs.append("en")

        max_available = max(chap_es, chap_en)
        chapters_needed = math.floor(chapters_read)
        chapters_ok = chapters_needed == 0 or max_available >= chapters_needed

        await database.update_result(
            manga_id=manga_id,
            mangadex_id=mdx_id,
            mangadex_url=mdx_url,
            match_score=round(best_score, 2),
            available_languages=available_langs,
            chapters_available_es=chap_es,
            chapters_available_en=chap_en,
            chapters_ok=chapters_ok,
            search_status="found",
        )
