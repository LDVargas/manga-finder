from dataclasses import dataclass
from pathlib import Path
from manga_finder.normalizer import normalize


@dataclass
class MangaEntry:
    title: str            # Best display title (preferring uppercase/Web source)
    title_normalized: str
    chapters_read: float
    status: str           # siguiendo | leyendo | pendiente | leido


_STATUS_PRIORITY = {"leido": 4, "leyendo": 3, "siguiendo": 2, "pendiente": 1}


def parse(filepath: str | Path) -> list[MangaEntry]:
    """Parse MIS_MANGAS_RESCATADOS.txt and return deduplicated manga entries."""
    path = Path(filepath)
    raw: dict[str, dict] = {}

    with path.open(encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i < 2:
                continue  # skip header rows
            line = line.strip()
            if not line:
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue

            source = parts[0]
            status = parts[1].lower()
            try:
                chapters = float(parts[2])
            except ValueError:
                chapters = 0.0
            title_raw = "|".join(parts[3:]).strip()

            key = normalize(title_raw)
            if not key:
                continue

            # Strip the Firefox duplicate suffix from the display title
            title_display = title_raw.rstrip().removesuffix("- -").rstrip(" -").strip()

            existing = raw.get(key)
            if existing is None:
                raw[key] = {
                    "title": title_display,
                    "chapters_read": chapters,
                    "status": status,
                    "source": source,
                }
            else:
                # Keep the Web/uppercase title as display title
                if source.lower() == "web":
                    existing["title"] = title_display
                # Keep max chapter progress
                if chapters > existing["chapters_read"]:
                    existing["chapters_read"] = chapters
                # Keep highest-priority status
                if _STATUS_PRIORITY.get(status, 0) > _STATUS_PRIORITY.get(existing["status"], 0):
                    existing["status"] = status

    return [
        MangaEntry(
            title=v["title"],
            title_normalized=k,
            chapters_read=v["chapters_read"],
            status=v["status"],
        )
        for k, v in raw.items()
    ]
