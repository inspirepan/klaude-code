"""Tests for the session holder (mutex) mechanism."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.control.runtime.actor import (
    HOLDER_GRACE_SECONDS,
    SessionActor,
)
from klaude_code.control.runtime.registry import SessionRegistry
from klaude_code.protocol import op

T = TypeVar("T")

def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)

# ── SessionActor holder tests ──

def _make_actor(session_id: str = "s1") -> SessionActor:
    async def _handle(_op: op.Operation) -> None:
        pass

    async def _reject(_op: op.Operation, _active: str | None) -> None:
        pass

    return SessionActor(session_id=session_id, handle_operation=_handle, reject_operation=_reject)

def test_acquire_holder_fresh() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.try_acquire_holder("key-a")
        assert actor.is_held_by("key-a")
        assert actor.get_holder_key() == "key-a"
        await actor.stop()

    arun(_test())

def test_acquire_same_key_is_idempotent() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.try_acquire_holder("key-a")
        assert actor.try_acquire_holder("key-a")
        assert actor.is_held_by("key-a")
        await actor.stop()

    arun(_test())

def test_acquire_different_key_denied() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.try_acquire_holder("key-a")
        assert not actor.try_acquire_holder("key-b")
        assert actor.is_held_by("key-a")
        assert not actor.is_held_by("key-b")
        await actor.stop()

    arun(_test())

def test_release_starts_grace_period() -> None:
    async def _test() -> None:
        actor = _make_actor()
        now = time.monotonic()
        assert actor.try_acquire_holder("key-a", now=now)
        assert actor.release_holder("key-a", now=now)

        # Holder is still "active" during grace period.
        assert actor.holder_is_active(now=now + 1.0)
        # But is_held_by returns False because released_at is set.
        assert not actor.is_held_by("key-a")

        # Another key cannot acquire during grace period.
        assert not actor.try_acquire_holder("key-b", now=now + 1.0)

        # After grace period, another key can acquire.
        assert actor.try_acquire_holder("key-b", now=now + HOLDER_GRACE_SECONDS + 0.1)
        assert actor.is_held_by("key-b")
        await actor.stop()

    arun(_test())

def test_reacquire_during_grace_period() -> None:
    async def _test() -> None:
        actor = _make_actor()
        now = time.monotonic()
        assert actor.try_acquire_holder("key-a", now=now)
        assert actor.release_holder("key-a", now=now)

        # Same key can reacquire during grace period.
        assert actor.try_acquire_holder("key-a", now=now + 2.0)
        assert actor.is_held_by("key-a")
        await actor.stop()

    arun(_test())

def test_same_key_denied_after_grace_period() -> None:
    async def _test() -> None:
        actor = _make_actor()
        now = time.monotonic()
        assert actor.try_acquire_holder("key-a", now=now)
        assert actor.release_holder("key-a", now=now)

        # Same key is also denied after grace period (must re-acquire fresh).
        after_grace = now + HOLDER_GRACE_SECONDS + 0.1
        assert not actor.holder_is_active(now=after_grace)
        # But since grace expired, any key (including original) can acquire anew.
        assert actor.try_acquire_holder("key-a", now=after_grace)
        assert actor.is_held_by("key-a")
        await actor.stop()

    arun(_test())

def test_force_release_clears_holder() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.try_acquire_holder("key-a")
        old = actor.force_release_holder()
        assert old == "key-a"
        assert actor.get_holder_key() is None
        assert not actor.holder_is_active()

        # Any key can now acquire.
        assert actor.try_acquire_holder("key-b")
        await actor.stop()

    arun(_test())

def test_release_wrong_key_noop() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.try_acquire_holder("key-a")
        assert not actor.release_holder("key-b")
        assert actor.is_held_by("key-a")
        await actor.stop()

    arun(_test())

def test_snapshot_includes_holder_key() -> None:
    async def _test() -> None:
        actor = _make_actor()
        assert actor.snapshot().holder_key is None
        actor.try_acquire_holder("key-a")
        assert actor.snapshot().holder_key == "key-a"
        await actor.stop()

    arun(_test())

# ── SessionRegistry holder tests ──

def _make_registry() -> SessionRegistry:
    async def _handle(_op: op.Operation) -> None:
        pass

    async def _reject(_op: op.Operation, _active: str | None) -> None:
        pass

    return SessionRegistry(handle_operation=_handle, reject_operation=_reject)

def test_registry_acquire_and_check() -> None:
    async def _test() -> None:
        registry = _make_registry()
        assert registry.try_acquire_holder("s1", "key-a")
        assert registry.is_held_by("s1", "key-a")
        assert not registry.is_held_by("s1", "key-b")
        assert registry.get_holder_key("s1") == "key-a"
        await registry.stop()

    arun(_test())

def test_registry_release_and_cleanup() -> None:
    async def _test() -> None:
        registry = _make_registry()
        assert registry.try_acquire_holder("s1", "key-a")
        assert registry.release_holder("s1", "key-a")
        assert not registry.is_held_by("s1", "key-a")
        assert registry.get_holder_key("s1") == "key-a"  # still set, in grace
        assert registry.holder_is_active("s1")  # grace period active

        # Cleanup stale holders manually (grace not expired yet).
        cleaned = registry.cleanup_stale_holders()
        assert "s1" not in cleaned

        await registry.stop()

    arun(_test())

def test_registry_force_release() -> None:
    async def _test() -> None:
        registry = _make_registry()
        assert registry.try_acquire_holder("s1", "key-a")
        old = registry.force_release_holder("s1")
        assert old == "key-a"
        assert registry.get_holder_key("s1") is None
        await registry.stop()

    arun(_test())

def test_registry_nonexistent_session() -> None:
    async def _test() -> None:
        registry = _make_registry()
        assert not registry.is_held_by("nonexistent", "key-a")
        assert registry.get_holder_key("nonexistent") is None
        assert not registry.holder_is_active("nonexistent")
        assert not registry.release_holder("nonexistent", "key-a")
        assert registry.force_release_holder("nonexistent") is None
        await registry.stop()

    arun(_test())
