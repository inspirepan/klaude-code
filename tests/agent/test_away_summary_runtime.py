# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import events, llm_param, message, op
from klaude_code.session.session import Session


class _FakeLLMClient(LLMClientABC):
    def __init__(self) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-fast",
            )
        )

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls()

    async def call(self, param: llm_param.LLMCallParameter) -> Any:
        raise AssertionError("generate_away_summary should be monkeypatched in this test")


def test_manual_recap_emits_spinner_events_but_auto_does_not(tmp_path: Path, monkeypatch: Any) -> None:
    async def _test() -> None:
        emitted: list[Any] = []
        client = _FakeLLMClient()

        async def _emit(event: Any) -> None:
            emitted.append(event)

        handler = AgentOperationHandler(
            emit_event=_emit,
            llm_clients=LLMClients(main=client, fast=client, compact=client),
            model_profile_provider=cast_any(object()),
            sub_agent_manager=cast_any(object()),
            on_child_task_state_change=_noop_child_task_state_change,
            ensure_session_actor=_unexpected_session_actor,
            get_session_actor=lambda _sid: None,
            get_session_actor_for_operation=lambda _op: None,
            list_session_actors=lambda: [],
            register_task=_noop_register_task,
            remove_task=_noop_remove_task,
            request_user_interaction=_noop_request_user_interaction,
        )

        session = Session(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("继续实现 recap"))])

        async def _ensure_agent(_session_id: str) -> Any:
            return cast_any(type("FakeAgent", (), {"session": session})())

        async def _fake_generate_away_summary(**_kwargs: Any) -> str:
            return "当前在调试 recap。已经定位到显示链路。下一步是收紧 spinner 行为。"

        def _fake_get_clients(_sid: str) -> LLMClients:
            return LLMClients(main=client, fast=client, compact=client)

        monkeypatch.setattr(handler, "ensure_agent", _ensure_agent)
        monkeypatch.setattr(handler, "get_session_llm_clients", _fake_get_clients)
        monkeypatch.setattr(
            "klaude_code.agent.runtime.agent_ops.generate_away_summary",
            _fake_generate_away_summary,
        )

        await handler.generate_away_summary(op.GenerateAwaySummaryOperation(session_id=session.id, source="manual"))
        assert len(emitted) == 3
        assert isinstance(emitted[0], events.AwaySummaryStartEvent)
        assert isinstance(emitted[1], events.AwaySummaryEvent)
        assert isinstance(emitted[2], events.AwaySummaryEndEvent)

        emitted.clear()
        session.conversation_history.clear()
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("继续实现 recap"))])

        await handler.generate_away_summary(op.GenerateAwaySummaryOperation(session_id=session.id, source="auto"))
        assert len(emitted) == 1
        assert isinstance(emitted[0], events.AwaySummaryEvent)

    asyncio.run(_test())


async def _noop_request_user_interaction(_request: Any) -> Any:
    raise RuntimeError("should not be called")


def _noop_child_task_state_change(_session_id: str, _task_id: str, _active: bool) -> None:
    return None


def _unexpected_session_actor(_sid: str) -> Any:
    raise RuntimeError("should not be called")


def _noop_register_task(_session_id: str, _operation_id: str, _task_id: str, _task: asyncio.Task[None]) -> None:
    return None


def _noop_remove_task(_session_id: str, _task_id: str) -> None:
    return None


def cast_any(value: object) -> Any:
    return value
