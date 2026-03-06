from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import pytest

from klaude_code.core.agent import runtime as runtime_mod
from klaude_code.protocol import events, op, user_interaction
from klaude_code.session.session import Session

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


class _FakeAgentRunner:
    def __init__(self, session: Session) -> None:
        self._agent = SimpleNamespace(session=session)

    async def ensure_agent(self, session_id: str) -> Any:
        assert session_id == self._agent.session.id
        return self._agent


def test_get_session_stats_operation_emits_status_event(tmp_path: Path) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        emitted: list[events.Event] = []

        async def _emit_event(event: events.Event) -> None:
            emitted.append(event)

        async def _request_user_interaction(
            _session_id: str,
            _request_id: str,
            _source: user_interaction.UserInteractionSource,
            _payload: user_interaction.UserInteractionRequestPayload,
        ) -> user_interaction.UserInteractionResponse:
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        handler = runtime_mod.ConfigHandler(
            agent_runner=cast(Any, _FakeAgentRunner(session)),
            model_switcher=cast(Any, object()),
            emit_event=_emit_event,
            request_user_interaction=_request_user_interaction,
            current_session_id=lambda: session.id,
            on_model_change=None,
        )

        await handler.handle_get_session_stats(op.GetSessionStatsOperation(session_id=session.id))
        assert len(emitted) == 1
        assert isinstance(emitted[0], events.SessionStatsEvent)
        assert emitted[0].stats.session_id == session.id

    arun(_test())
