# pyright: reportPrivateUsage=false, reportUnusedFunction=false

"""Tests for command registry dispatch matching."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from klaude_code.protocol import commands, message, op
from klaude_code.tui.command import registry
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult


def arun(coro: Any) -> Any:
    """Helper to run async coroutines."""

    return asyncio.run(coro)


class _DummyCommand(CommandABC):
    def __init__(self, name: commands.CommandName | str, action_text: str, *, interactive: bool = False):
        self._name = name
        self._action_text = action_text
        self._interactive = interactive

    @property
    def name(self) -> commands.CommandName | str:
        return self._name

    @property
    def summary(self) -> str:
        return "dummy"

    @property
    def is_interactive(self) -> bool:
        return self._interactive

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del agent  # unused
        return CommandResult(
            operations=[
                op.RunAgentOperation(
                    session_id="dummy",
                    input=message.UserInputPayload(
                        text=f"{self._action_text}:{user_input.text}", images=user_input.images
                    ),
                )
            ]
        )


class _DummyAgent:
    # Only needed for error-path in dispatch; not used in these tests.
    session = type("Sess", (), {"id": "dummy"})()  # type: ignore[assignment]
    profile = None

    def get_llm_client(self) -> Any:
        raise NotImplementedError


@pytest.fixture
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> dict[commands.CommandName | str, CommandABC]:
    monkeypatch.setattr(registry, "_ensure_commands_loaded", lambda: None)
    commands_map: dict[commands.CommandName | str, CommandABC] = {}
    monkeypatch.setattr(registry, "_COMMANDS", commands_map)
    return commands_map


def test_dispatch_prefix_prefers_base_command_when_other_is_extension(
    _isolated_registry: dict[commands.CommandName | str, CommandABC],
) -> None:
    _isolated_registry[commands.CommandName.EXPORT] = _DummyCommand(commands.CommandName.EXPORT, "export")
    _isolated_registry[commands.CommandName.EXPORT_ONLINE] = _DummyCommand(
        commands.CommandName.EXPORT_ONLINE,
        "export-online",
    )

    result = arun(
        registry.dispatch_command(
            message.UserInputPayload(text="/exp foo"), cast(Agent, _DummyAgent()), submission_id="s1"
        )
    )
    assert result.operations is not None
    assert isinstance(result.operations[0], op.RunAgentOperation)
    assert result.operations[0].input.text == "export:foo"


def test_dispatch_prefix_can_target_extension_command(
    _isolated_registry: dict[commands.CommandName | str, CommandABC],
) -> None:
    _isolated_registry[commands.CommandName.EXPORT] = _DummyCommand(commands.CommandName.EXPORT, "export")
    _isolated_registry[commands.CommandName.EXPORT_ONLINE] = _DummyCommand(
        commands.CommandName.EXPORT_ONLINE,
        "export-online",
    )

    result = arun(
        registry.dispatch_command(
            message.UserInputPayload(text="/export-o bar"), cast(Agent, _DummyAgent()), submission_id="s1"
        )
    )
    assert result.operations is not None
    assert isinstance(result.operations[0], op.RunAgentOperation)
    assert result.operations[0].input.text == "export-online:bar"


def test_slash_command_name_supports_prefix_match(
    _isolated_registry: dict[commands.CommandName | str, CommandABC],
) -> None:
    _isolated_registry[commands.CommandName.EXPORT] = _DummyCommand(commands.CommandName.EXPORT, "export")
    _isolated_registry[commands.CommandName.EXPORT_ONLINE] = _DummyCommand(
        commands.CommandName.EXPORT_ONLINE,
        "export-online",
    )

    assert registry.is_slash_command_name("exp") is True
    assert registry.is_slash_command_name("export-o") is True


def test_dispatch_ambiguous_prefix_falls_back_to_agent(
    _isolated_registry: dict[commands.CommandName | str, CommandABC],
) -> None:
    _isolated_registry["exit"] = _DummyCommand("exit", "exit")
    _isolated_registry["export"] = _DummyCommand("export", "export")

    result = arun(
        registry.dispatch_command(
            message.UserInputPayload(text="/ex something"), cast(Agent, _DummyAgent()), submission_id="s1"
        )
    )
    assert result.operations is not None
    assert isinstance(result.operations[0], op.RunAgentOperation)
    assert result.operations[0].input.text == "/ex something"
