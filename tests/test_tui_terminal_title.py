from __future__ import annotations

from collections.abc import Sequence

import pytest

from klaude_code.protocol import events
from klaude_code.protocol.llm_param import LLMClientProtocol, LLMConfigParameter
from klaude_code.tui.commands import StartTitleBlink, UpdateTerminalTitlePrefix
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.terminal import title as terminal_title


def _llm_config() -> LLMConfigParameter:
    return LLMConfigParameter(
        protocol=LLMClientProtocol.OPENAI,
        provider_name="demo",
        model_id="gpt-demo",
    )

def _last_title_cmd(cmds: Sequence[object]) -> UpdateTerminalTitlePrefix:
    matches = [cmd for cmd in cmds if isinstance(cmd, UpdateTerminalTitlePrefix)]
    assert matches
    return matches[-1]

def test_welcome_updates_terminal_title_with_session_title() -> None:
    machine = DisplayStateMachine()
    machine.set_model_name("gpt-5")

    cmds = machine.transition(
        events.WelcomeEvent(
            session_id="s1",
            work_dir="/tmp/project",
            llm_config=_llm_config(),
            title="Fix session title generation",
        )
    )

    cmd = _last_title_cmd(cmds)
    assert cmd.prefix is None
    assert cmd.model_name == "gpt-5"
    assert cmd.session_title == "Fix session title generation"

def test_title_change_preserves_active_terminal_prefix() -> None:
    machine = DisplayStateMachine()
    machine.set_model_name("gpt-5")
    machine.transition(
        events.WelcomeEvent(
            session_id="s1",
            work_dir="/tmp/project",
            llm_config=_llm_config(),
            title="Old title",
        )
    )

    start_cmds = machine.transition(events.TaskStartEvent(session_id="s1", model_id="gpt-5"))
    blink_cmds = [cmd for cmd in start_cmds if isinstance(cmd, StartTitleBlink)]
    assert len(blink_cmds) == 1
    assert blink_cmds[0].model_name == "gpt-5"
    assert blink_cmds[0].session_title == "Old title"

    update_cmds = machine.transition(events.SessionTitleChangedEvent(session_id="s1", title="New title"))
    update_title_cmd = _last_title_cmd(update_cmds)
    assert update_title_cmd.prefix == "\u26ac"
    assert update_title_cmd.session_title == "New title"

def test_update_terminal_title_prefers_session_title(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    monkeypatch.setattr(terminal_title, "set_terminal_title", captured.append)

    terminal_title.update_terminal_title(
        model_name="gpt-5@openai",
        prefix="✔",
        work_dir="/tmp/project",
        session_title="生成的标题",
    )

    assert captured == ["✔ 生成的标题"]
