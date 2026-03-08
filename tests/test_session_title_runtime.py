# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from klaude_code.core.agent.runtime import AgentOperationHandler, LLMClients, _generate_session_title
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session, close_default_store


class _FakeStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items

    async def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _FakeLLMClient(LLMClientABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-compact",
            )
        )
        self.items = items
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls([])

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        return _FakeStream(self.items)


def test_generate_session_title_uses_only_user_messages() -> None:
    client = _FakeLLMClient(
        [
            message.AssistantMessage(parts=[message.TextPart(text='  "Fix session title generation"  ')], stop_reason="stop")
        ]
    )

    title = asyncio.run(
        _generate_session_title(
            llm_client=client,
            user_messages=["first request", "latest request about src/app.py"],
        )
    )

    assert title == "Fix session title generation"
    assert len(client.calls) == 1
    rendered = message.join_text_parts(client.calls[0].input[0].parts)
    assert "first request" in rendered
    assert "latest request about src/app.py" in rendered
    assert "assistant" not in rendered.lower()
    assert client.calls[0].system is not None
    assert "same language" in client.calls[0].system.lower()


def test_schedule_session_title_refresh_runs_in_background(tmp_path: Path) -> None:
    async def _test() -> None:
        client = _FakeLLMClient([])
        handler = AgentOperationHandler(
            emit_event=_noop_emit,
            llm_clients=LLMClients(main=client, compact=client),
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
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("分析一下 session 标题"))])

        started = asyncio.Event()
        release = asyncio.Event()

        async def _fake_refresh(_session: Session, *, user_messages_snapshot: list[str]) -> None:
            assert user_messages_snapshot == ["分析一下 session 标题"]
            started.set()
            await release.wait()

        handler._refresh_session_title = _fake_refresh  # type: ignore[method-assign]
        handler._schedule_session_title_refresh(session)

        await asyncio.wait_for(started.wait(), timeout=1)
        assert session.id in handler._title_refresh_tasks
        assert not handler._title_refresh_tasks[session.id].done()

        release.set()
        await handler._title_refresh_tasks[session.id]
        await close_default_store()

    asyncio.run(_test())


async def _noop_emit(_event: Any) -> None:
    return None


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
