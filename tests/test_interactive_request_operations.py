# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import pytest

from klaude_code.agent import runtime_config_ops as runtime_mod
from klaude_code.config.model_matcher import ModelMatchResult
from klaude_code.protocol import events, op, user_interaction
from klaude_code.session.session import Session

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


class _FakeAgentRunner:
    def __init__(self, session: Session) -> None:
        self._agent = SimpleNamespace(session=session)
        self._llm_clients = SimpleNamespace(
            main=SimpleNamespace(model_name="main-model"),
            fast=None,
            compact=None,
            sub_clients={},
        )

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

    def get_session_llm_clients(self, session_id: str) -> Any:
        assert session_id == self._agent.session.id
        return self._llm_clients


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


def test_request_model_operation_no_match_emits_notice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        emitted: list[events.Event] = []
        handler = _build_handler(
            session=session,
            emitted=emitted,
            interaction_response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )

        def _match_model(_preferred: str | None) -> ModelMatchResult:
            return ModelMatchResult(
                matched_model=None,
                filtered_models=[],
                filter_hint="does-not-exist",
            )

        monkeypatch.setattr(runtime_mod, "match_model_from_config", _match_model)

        await handler.handle_request_model(op.RequestModelOperation(session_id=session.id, preferred="does-not-exist"))
        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].content == "(no match)"
        assert emitted[0].is_error is False

    arun(_test())


def test_request_model_operation_uses_initial_search_text_for_picker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        emitted: list[events.Event] = []
        runner = _FakeAgentRunner(session)
        request_payloads: list[user_interaction.UserInteractionRequestPayload] = []
        match_calls: list[str | None] = []

        model_entries = [
            SimpleNamespace(
                selector="gpt-5.4@openai",
                provider="openai",
                model_id="gpt-5.4",
                model_name="gpt-5.4",
            ),
            SimpleNamespace(
                selector="claude-sonnet-4-6@anthropic",
                provider="anthropic",
                model_id="claude-sonnet-4-6",
                model_name="sonnet",
            ),
        ]

        async def _emit_event(event: events.Event) -> None:
            emitted.append(event)

        async def _request_user_interaction(
            _session_id: str,
            _request_id: str,
            _source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
        ) -> user_interaction.UserInteractionResponse:
            request_payloads.append(payload)
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        def _match_model(preferred: str | None) -> ModelMatchResult:
            match_calls.append(preferred)
            return ModelMatchResult(
                matched_model=None,
                filtered_models=cast(Any, model_entries),
                filter_hint=None,
            )

        monkeypatch.setattr(runtime_mod, "match_model_from_config", _match_model)

        handler = runtime_mod.ConfigHandler(
            agent_runner=cast(Any, runner),
            model_switcher=cast(Any, object()),
            emit_event=_emit_event,
            request_user_interaction=_request_user_interaction,
            current_session_id=lambda: session.id,
            on_model_change=None,
        )

        await handler.handle_request_model(
            op.RequestModelOperation(session_id=session.id, initial_search_text=" sonnet ")
        )

        assert match_calls == [None]
        assert len(request_payloads) == 1
        payload = cast(user_interaction.OperationSelectRequestPayload, request_payloads[0])
        assert payload.initial_search_text == "sonnet"
        assert len(payload.options) == 2

        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].content == "(no change)"

    arun(_test())


def test_request_model_operation_same_runtime_model_still_saves_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.model_config_name = "gpt@openai"
        emitted: list[events.Event] = []
        handler = _build_handler(
            session=session,
            emitted=emitted,
            interaction_response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )

        def _match_model(_preferred: str | None) -> ModelMatchResult:
            return ModelMatchResult(
                matched_model="gpt@openai",
                filtered_models=[],
                filter_hint=None,
            )

        class _FakeConfig:
            def __init__(self) -> None:
                self.main_model = "opus@anthropic"
                self.saved = False

            async def save(self) -> None:
                self.saved = True

        fake_config = _FakeConfig()
        monkeypatch.setattr(runtime_mod, "match_model_from_config", _match_model)
        monkeypatch.setattr(runtime_mod, "load_config", lambda: cast(Any, fake_config))

        async def _unexpected_change(_change_op: op.ChangeModelOperation) -> None:
            raise AssertionError("should not reapply the current model when only saving default")

        monkeypatch.setattr(handler, "handle_change_model", _unexpected_change)

        await handler.handle_request_model(op.RequestModelOperation(session_id=session.id, preferred="gpt"))

        assert fake_config.main_model == "gpt@openai"
        assert fake_config.saved is True
        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].content == "Main model: gpt@openai (saved in ~/.klaude/klaude-config.yaml)"

    arun(_test())


def test_request_sub_agent_model_operation_selects_fast_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        emitted: list[events.Event] = []
        runner = _FakeAgentRunner(session)
        request_payloads: list[user_interaction.UserInteractionRequestPayload] = []
        selected_option_ids = iter(["__fast__", "fast-model@openai"])

        class _FakeConfig:
            def __init__(self) -> None:
                self.main_model = "main-model"
                self.fast_model: str | list[str] | None = None
                self.compact_model: str | list[str] | None = None
                self.sub_agent_models: dict[str, str] = {}
                self.saved = False

            def iter_model_entries(self, *, only_available: bool, include_disabled: bool) -> list[Any]:
                assert only_available is True
                assert include_disabled is False
                return [
                    SimpleNamespace(
                        selector="fast-model@openai",
                        provider="openai",
                        model_id="fast-model-id",
                        model_name="fast-model",
                    )
                ]

            def get_model_config(self, model_name: str) -> Any:
                assert model_name == "fast-model@openai"
                return SimpleNamespace(model_name=model_name)

            async def save(self) -> None:
                self.saved = True

        fake_config = _FakeConfig()

        async def _emit_event(event: events.Event) -> None:
            emitted.append(event)

        async def _request_user_interaction(
            _session_id: str,
            _request_id: str,
            _source: user_interaction.UserInteractionSource,
            payload: user_interaction.UserInteractionRequestPayload,
        ) -> user_interaction.UserInteractionResponse:
            request_payloads.append(payload)
            return user_interaction.UserInteractionResponse(
                status="submitted",
                payload=user_interaction.OperationSelectResponsePayload(
                    selected_option_id=next(selected_option_ids),
                ),
            )

        monkeypatch.setattr(runtime_mod, "load_config", lambda: cast(Any, fake_config))

        def _create_llm_client(_llm_config: Any) -> Any:
            return SimpleNamespace(model_name="fast-model-id")

        monkeypatch.setattr(
            runtime_mod,
            "create_llm_client",
            _create_llm_client,
        )

        handler = runtime_mod.ConfigHandler(
            agent_runner=cast(Any, runner),
            model_switcher=cast(Any, object()),
            emit_event=_emit_event,
            request_user_interaction=_request_user_interaction,
            current_session_id=lambda: session.id,
            on_model_change=None,
        )

        await handler.handle_request_sub_agent_model(
            op.RequestSubAgentModelOperation(session_id=session.id, save_as_default=True)
        )

        assert len(request_payloads) == 2
        top_level_payload = cast(user_interaction.OperationSelectRequestPayload, request_payloads[0])
        top_level_ids = [item.id for item in top_level_payload.options]
        assert "__fast__" in top_level_ids

        fast_payload = cast(user_interaction.OperationSelectRequestPayload, request_payloads[1])
        assert fast_payload.header == "Fast"

        assert runner.get_session_llm_clients(session.id).fast is not None
        assert runner.get_session_llm_clients(session.id).fast.model_name == "fast-model-id"
        assert fake_config.fast_model == "fast-model@openai"
        assert fake_config.saved is True

        assert len(emitted) == 1
        assert isinstance(emitted[0], events.NoticeEvent)
        assert emitted[0].content == "Fast model: fast-model-id (saved in ~/.klaude/klaude-config.yaml)"

    arun(_test())
