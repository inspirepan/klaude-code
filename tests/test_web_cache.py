from __future__ import annotations

from unittest.mock import patch

from klaude_code.core.tool.web.web_cache import (
    _cache,  # pyright: ignore[reportPrivateUsage]
    get_cached,
    make_cache_key,
    set_cached,
)


class TestMakeCacheKey:
    def test_basic(self) -> None:
        assert make_cache_key("search", "python") == "search|python"

    def test_normalization(self) -> None:
        assert make_cache_key("SEARCH", " Python ") == "search|python"

    def test_multiple_parts(self) -> None:
        assert make_cache_key("fetch", "https://Example.COM", "extra") == "fetch|https://example.com|extra"


class TestCacheGetSet:
    def setup_method(self) -> None:
        _cache.clear()

    def test_miss(self) -> None:
        assert get_cached("nonexistent") is None

    def test_hit(self) -> None:
        set_cached("key1", "value1")
        assert get_cached("key1") == "value1"

    def test_expired(self) -> None:
        # Use a fixed monotonic time: set at t=100, expires at t=100+900=1000
        with patch("klaude_code.core.tool.web.web_cache.monotonic", return_value=100.0):
            set_cached("key2", "value2")
        # Read at t=1001, expired
        with patch("klaude_code.core.tool.web.web_cache.monotonic", return_value=1001.0):
            assert get_cached("key2") is None

    def test_not_expired(self) -> None:
        with patch("klaude_code.core.tool.web.web_cache.monotonic", return_value=100.0):
            set_cached("key3", "value3")
        with patch("klaude_code.core.tool.web.web_cache.monotonic", return_value=999.0):
            assert get_cached("key3") == "value3"

    def test_max_entries_eviction(self) -> None:
        _cache.clear()
        with patch("klaude_code.core.tool.web.web_cache.WEB_CACHE_MAX_ENTRIES", 3):
            set_cached("a", 1)
            set_cached("b", 2)
            set_cached("c", 3)
            assert len(_cache) == 3

            # Adding one more should evict the oldest
            set_cached("d", 4)
            # "a" should be evicted (it was inserted first)
            assert "a" not in _cache
            assert get_cached("d") == 4

    def test_overwrite(self) -> None:
        set_cached("key", "old")
        set_cached("key", "new")
        assert get_cached("key") == "new"
