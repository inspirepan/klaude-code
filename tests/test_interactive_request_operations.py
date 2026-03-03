# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import pytest

from klaude_code.config.model_matcher import ModelMatchResult
from klaude_code.core.agent import runtime as runtime_mod
from klaude_code.protocol import events, op, user_interaction
from klaude_code.session.session import Session

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    async def run_background_operation(
        self,
        *,
        operation_id: str,
        session_id: str,
        runner: Callable[[], Awaitable[None]],
    ) -> None:
        del operation_id
        assert session_id == self._agent.session.id
        await runner()


def _build_handler(
    *,
    session: Session,
    emitted: list[events.Event],
    interaction_response: user_interaction.UserInteractionResponse,
) -> runtime_mod.ConfigHandler:
    async def _emit_event(event: events.Event) -> None:
        emitted.append(event)

    async def _request_user_interaction(
        _session_id: str,
        _request_id: str,
        _source: user_interaction.UserInteractionSource,
        _payload: user_interaction.UserInteractionRequestPayload,
    ) -> user_interaction.UserInteractionResponse:
        return interaction_response

    return runtime_mod.ConfigHandler(
        agent_runner=cast(Any, _FakeAgentRunner(session)),
        model_switcher=cast(Any, object()),
        emit_event=_emit_event,
        request_user_interaction=_request_user_interaction,
        current_session_id=lambda: session.id,
        on_model_change=None,
    )


def test_request_model_operation_single_match_dispatches_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.model_config_name = "old-model"
        emitted: list[events.Event] = []
        handler = _build_handler(
            session=session,
            emitted=emitted,
            interaction_response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )

        def _match_model(_preferred: str | None) -> ModelMatchResult:
            return ModelMatchResult(
                matched_model="new-model",
                filtered_models=[],
                filter_hint=None,
            )

        monkeypatch.setattr(runtime_mod, "match_model_from_config", _match_model)

        captured: list[op.ChangeModelOperation] = []

        async def _capture_change(change_op: op.ChangeModelOperation) -> None:
            captured.append(change_op)

        monkeypatch.setattr(handler, "handle_change_model", _capture_change)

        await handler.handle_request_model(op.RequestModelOperation(session_id=session.id, preferred="new"))
        assert len(captured) == 1
        assert captured[0].model_name == "new-model"
        assert emitted == []

    arun(_test())


def test_request_model_operation_cancelled_emits_no_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        emitted: list[events.Event] = []
        handler = _build_handler(
            session=session,
            emitted=emitted,
            interaction_response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )

        model_entry: Any = SimpleNamespace(
            selector="model-a",
            provider="openai",
            model_id="gpt-5.2",
            model_name="gpt-5.2",
        )

        def _match_model(_preferred: str | None) -> ModelMatchResult:
            return ModelMatchResult(
                matched_model=None,
                filtered_models=cast(Any, [model_entry]),
                filter_hint=None,
            )

        monkeypatch.setattr(runtime_mod, "match_model_from_config", _match_model)

        await handler.handle_request_model(op.RequestModelOperation(session_id=session.id))
        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].content == "(no change)"

    arun(_test())
