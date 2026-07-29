import asyncio
from typing import Any, cast

from klaude_code.protocol import message, op
from klaude_code.tui.command import has_background_command
from klaude_code.tui.command.btw_cmd import BtwCommand
from klaude_code.tui.command.command_abc import Agent
from klaude_code.tui.command.types import CommandName


class _DummyAgent:
    session = type("Session", (), {"id": "session-1"})()
    profile = None

    def get_llm_client(self) -> Any:
        raise NotImplementedError


def test_btw_command_submits_side_question_operation() -> None:
    command = BtwCommand()

    result = asyncio.run(command.run(cast(Agent, _DummyAgent()), message.UserInputPayload(text="why is this cached?")))

    assert command.name is CommandName.BTW
    assert command.support_addition_params is True
    assert command.runs_in_background is True
    assert result.operations is not None
    assert len(result.operations) == 1
    operation = result.operations[0]
    assert isinstance(operation, op.AskSideQuestionOperation)
    assert operation.session_id == "session-1"
    assert operation.question == "why is this cached?"


def test_btw_command_passes_empty_question_to_the_runtime_guard() -> None:
    """Emptiness is rejected by the operation handler, not by the TUI."""
    command = BtwCommand()

    result = asyncio.run(command.run(cast(Agent, _DummyAgent()), message.UserInputPayload(text="   ")))

    assert result.operations is not None
    operation = result.operations[0]
    assert isinstance(operation, op.AskSideQuestionOperation)
    assert operation.question.strip() == ""


def test_only_btw_is_dispatched_in_background() -> None:
    assert has_background_command("/btw why?") is True
    assert has_background_command("/btw") is True
    assert has_background_command("/recap") is False
    assert has_background_command("plain text") is False
