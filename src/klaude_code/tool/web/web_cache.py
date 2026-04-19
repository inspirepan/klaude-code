"""In-memory TTL cache for web search and fetch results."""

from __future__ import annotations

from time import monotonic
from typing import Any

from klaude_code.const import WEB_CACHE_MAX_ENTRIES, WEB_CACHE_TTL_SECONDS

_cache: dict[str, tuple[float, Any]] = {}


def get_cached(key: str) -> Any | None:
    """Return cached value if present and not expired, else None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return value


def set_cached(key: str, value: Any) -> None:
    """Store a value in cache with TTL."""
    if len(_cache) >= WEB_CACHE_MAX_ENTRIES:
        oldest = next(iter(_cache))
        del _cache[oldest]
    _cache[key] = (monotonic() + WEB_CACHE_TTL_SECONDS, value)


def make_cache_key(*parts: str) -> str:
    """Build a normalized cache key from parts."""
    return "|".join(p.strip().lower() for p in parts)
