from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import message, op
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session.session import Session


def test_run_agent_resumes_without_duplicate_user_message(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session.create(work_dir=tmp_path)
        operation = op.RunAgentOperation(
            id="persisted-turn", session_id=session.id, input=UserInputPayload(text="resume")
        )
        session.append_history(
            [message.UserMessage(id=operation.id, parts=message.text_parts_from_str(operation.input.text))]
        )
        await session.wait_for_flush()
        agent = cast(Any, type("FakeAgent", (), {"session": session})())
        handler = cast(Any, object.__new__(AgentOperationHandler))
        task_ran = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []

        async def _ensure_agent(_session_id: str) -> Any:
            return agent

        async def _emit_event(_event: Any) -> None:
            return None

        async def _run_agent_task(*_args: Any) -> None:
            task_ran.set()

        async def _unexpected_freeze(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("persisted user input must not be appended again")

        handler.ensure_agent = _ensure_agent
        handler._cancel_prompt_suggestion = lambda _session_id: None
        handler._cancel_auto_away_summary = lambda _session_id: None
        handler._emit_event = _emit_event
        handler._freeze_user_input_for_history = _unexpected_freeze
        handler._should_refresh_session_title_during_task = lambda _session_id: False
        handler.get_active_task = lambda _operation_id: None
        handler._run_agent_task = _run_agent_task
        handler._register_task = lambda **kwargs: tasks.append(kwargs["task"])

        await handler.run_agent(operation)
        await asyncio.gather(*tasks)

        assert task_ran.is_set()
        assert [item.id for item in session.conversation_history if isinstance(item, message.UserMessage)] == [
            operation.id
        ]

    asyncio.run(_test())
