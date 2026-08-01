import asyncio
from typing import Any, cast

import pytest

import klaude_code.tui.command.grill_me_cmd as grill_me_module
from klaude_code.protocol import message, op
from klaude_code.tui.command.command_abc import Agent
from klaude_code.tui.command.grill_me_cmd import GrillMeCommand
from klaude_code.tui.command.types import CommandName


class _DummyAgent:
    session = type("Session", (), {"id": "session-1"})()
    profile = None

    def get_llm_client(self) -> Any:
        raise NotImplementedError


def test_grill_me_command_starts_interview_for_current_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grill_me_module, "GRILLING_PROMPT", "GRILL_SENTINEL")
    command = GrillMeCommand()

    result = asyncio.run(command.run(cast(Agent, _DummyAgent()), message.UserInputPayload(text="")))

    assert command.name is CommandName.GRILL_ME
    assert command.support_addition_params is True
    assert result.operations is not None
    assert len(result.operations) == 1
    operation = result.operations[0]
    assert isinstance(operation, op.RunAgentOperation)
    assert operation.session_id == "session-1"
    assert operation.input.text == "GRILL_SENTINEL"


def test_grill_me_command_appends_supplied_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(grill_me_module, "GRILLING_PROMPT", "GRILL_SENTINEL")
    command = GrillMeCommand()

    result = asyncio.run(
        command.run(cast(Agent, _DummyAgent()), message.UserInputPayload(text="  whether to rewrite the parser  "))
    )

    assert result.operations is not None
    operation = result.operations[0]
    assert isinstance(operation, op.RunAgentOperation)
    assert operation.input.text.startswith("GRILL_SENTINEL")
    assert operation.input.text.endswith("whether to rewrite the parser")
