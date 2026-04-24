from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any, cast

from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent
from klaude_code.tui.command.model_cmd import ModelCommand


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class _DummyAgent:
    session = SimpleNamespace(id="session-1")
    profile = None

    def get_llm_client(self) -> object:
        raise NotImplementedError


def test_model_command_changes_model_and_saves_default() -> None:
    command = ModelCommand()

    result = arun(command.run(cast(Agent, _DummyAgent()), message.UserInputPayload(text="gpt-5.4")))

    assert result.operations is not None
    assert len(result.operations) == 1
    assert isinstance(result.operations[0], op.RequestModelOperation)
    assert result.operations[0].save_as_default is True
    assert result.operations[0].initial_search_text == "gpt-5.4"