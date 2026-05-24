import re
import unicodedata


def normalize(title: str) -> str:
    """Normalize a manga title for deduplication and fuzzy matching."""
    t = title.strip()
    # Remove the Firefox duplicate suffix
    t = re.sub(r'\s*-\s*-\s*$', '', t)
    # Lowercase
    t = t.lower()
    # Remove accents
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    # Replace common punctuation/symbols with spaces
    t = re.sub(r'[^\w\s]', ' ', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t
