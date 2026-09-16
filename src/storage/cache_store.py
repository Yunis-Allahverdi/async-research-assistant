"""Filesystem JSON cache for (origin, query) -> sources.

We never fetch the same (source, query) twice within the TTL: we write the
result to a small JSON file on disk and read it back on the next identical
request. Keys are canonicalised so "WHAT IS X?" and "what is x" hit the same
entry.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from ai import Source
from src.config import Settings
from src.models import CacheEntry


def make_key(origin: str, query: str) -> str:
    """Turn (origin, query) into one stable, filesystem-safe key.

    Canonicalise the query (lowercase + strip) so equivalent questions match,
    then hash it so odd characters (?, /, spaces) can't break the filename.
    """
    canonical = f"{origin.lower().strip()}|{query.lower().strip()}"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{origin}_{digest}"

def _cache_path(key: str, settings: Settings) -> Path:
    """Full path to the JSON file for this key."""
    return Path(settings.cache_dir) / f"{key}.json"


def write(entry: CacheEntry, *, settings: Settings) -> None:
    """Write one cache entry to disk as JSON."""
    directory = Path(settings.cache_dir)
    directory.mkdir(parents=True, exist_ok=True)   # create .cache/ if missing
    path = _cache_path(entry.key, settings)
    data = entry.model_dump()                       # pydantic -> plain dict
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

def read(key: str, *, settings: Settings) -> CacheEntry | None:
    """Read a cache entry by key, or None if missing or expired (older than TTL)."""
    path = _cache_path(key, settings)
    if not path.exists():
        return None                                 # case 1: never cached

    data = json.loads(path.read_text(encoding="utf-8"))
    entry = CacheEntry.model_validate(data)         # plain dict -> pydantic

    age = time.time() - entry.created_at
    if age > settings.cache_ttl:
        return None                                 # case 2: too old, treat as miss

    return entry                                    # case 3: fresh hit