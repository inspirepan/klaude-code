from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from klaude_code.protocol import events
from klaude_code.protocol.models import SubAgentState, TaskMetadata, TaskMetadataItem, Usage
from klaude_code.tui import runner as runner_module
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input.key_bindings import create_key_bindings
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.runner import toggle_transcript_view
from klaude_code.tui.transcript_detail import Detail


class _Display:
    def __init__(self) -> None:
        self.toggle_count = 0

    def toggle_transcript_mode(self) -> bool:
        self.toggle_count += 1
        return False


def test_ctrl_o_requests_transcript_toggle() -> None:
    calls: list[None] = []
    bindings = create_key_bindings(
        capture_clipboard_tag=lambda: None,
        at_token_pattern=re.compile(r"$^"),
        skill_token_pattern=re.compile(r"$^"),
        request_toggle_transcript=lambda: calls.append(None),
    )

    binding = bindings.get_bindings_for_keys((Keys.ControlO,))[-1]
    binding.handler(cast(KeyPressEvent, SimpleNamespace()))

    assert calls == [None]


def test_compact_renderer_hides_sub_agent_body_and_expanded_restores_it() -> None:
    renderer = TUICommandRenderer()
    event = events.TaskStartEvent(
        session_id="child",
        model_id="test-model",
        sub_agent_state=SubAgentState(
            sub_agent_type="finder",
            sub_agent_desc="inspect replay",
            sub_agent_prompt="Read every relevant file",
        ),
    )

    with renderer.bulk_render_capture() as compact:
        renderer.display_task_start(event)
    assert compact.getvalue() == ""

    renderer.set_transcript_detail(Detail.FULL)
    renderer.reset_replay_state()
    with renderer.bulk_render_capture() as expanded:
        renderer.display_task_start(event)
    assert "inspect replay" in expanded.getvalue()
    assert "Read every relevant file" in expanded.getvalue()


def test_renderer_switches_task_metadata_between_compact_and_expanded() -> None:
    renderer = TUICommandRenderer()
    event = events.TaskMetadataEvent(
        session_id="main",
        metadata=TaskMetadataItem(
            main_agent=TaskMetadata(
                model_name="test-model",
                usage=Usage(input_tokens=30_000, cached_tokens=20_000, output_tokens=2_000),
                step_count=2,
                task_duration_s=18,
            )
        ),
    )

    with renderer.bulk_render_capture() as compact:
        renderer.display_task_metadata(event)
    assert "• test-model ↑10k ◎20k ↓2k 18s" in compact.getvalue()
    assert "2 steps" not in compact.getvalue()

    renderer.set_transcript_detail(Detail.FULL)
    with renderer.bulk_render_capture() as expanded:
        renderer.display_task_metadata(event)
    assert "in 10k cache 20k out 2k" in expanded.getvalue()
    assert "2 steps" in expanded.getvalue()


def test_renderer_switches_error_detail_between_compact_and_expanded() -> None:
    renderer = TUICommandRenderer()
    event = events.ErrorEvent(
        session_id="main",
        error_message=(
            "Prompt cache break detected: likely server-side\n"
            "Cached tokens: 138,752 -> 2,560 (drop: 136,192)\n"
            "Report: /tmp/cache-break.txt"
        ),
        compact_message="Prompt cache break detected: likely server-side",
        can_retry=True,
    )

    with renderer.bulk_render_capture() as compact:
        renderer.display_error(event)
    assert "Prompt cache break detected: likely server-side" in compact.getvalue()
    assert "Cached tokens:" not in compact.getvalue()
    assert "Report:" not in compact.getvalue()

    renderer.set_transcript_detail(Detail.FULL)
    with renderer.bulk_render_capture() as expanded:
        renderer.display_error(event)
    assert "Cached tokens: 138,752 -> 2,560 (drop: 136,192)" in expanded.getvalue()
    assert "Report: /tmp/cache-break.txt" in expanded.getvalue()


def test_display_toggle_is_process_local() -> None:
    display = TUIDisplay()
    assert display.compact_transcript is True
    assert display.toggle_transcript_mode() is False
    assert display.compact_transcript is False
    assert TUIDisplay().compact_transcript is True


def test_toggle_transcript_replays_when_idle(monkeypatch: Any) -> None:
    async def _test() -> None:
        runtime = SimpleNamespace(
            current_session_id=lambda: "session-1",
            emit_event=AsyncMock(),
            replay_session_history=AsyncMock(),
        )
        display = _Display()
        wait_for_display_idle = AsyncMock()
        settle = AsyncMock()
        monkeypatch.setattr(runner_module, "settle_flicker_safe_stdout", settle)

        toggled = await toggle_transcript_view(
            runtime=cast(Any, runtime),
            display=cast(Any, display),
            is_agent_running=lambda: False,
            wait_for_display_idle=wait_for_display_idle,
        )

        assert toggled is True
        assert display.toggle_count == 1
        runtime.replay_session_history.assert_awaited_once_with("session-1")
        wait_for_display_idle.assert_awaited_once()
        settle.assert_awaited_once()

    asyncio.run(_test())


def test_toggle_transcript_is_rejected_while_running(monkeypatch: Any) -> None:
    async def _test() -> None:
        runtime = SimpleNamespace(
            current_session_id=lambda: "session-1",
            emit_event=AsyncMock(),
            replay_session_history=AsyncMock(),
        )
        display = _Display()
        settle = AsyncMock()
        monkeypatch.setattr(runner_module, "settle_flicker_safe_stdout", settle)

        toggled = await toggle_transcript_view(
            runtime=cast(Any, runtime),
            display=cast(Any, display),
            is_agent_running=lambda: True,
            wait_for_display_idle=AsyncMock(),
        )

        assert toggled is False
        assert display.toggle_count == 0
        runtime.replay_session_history.assert_not_awaited()
        emitted = runtime.emit_event.await_args.args[0]
        assert isinstance(emitted, events.NoticeEvent)
        assert emitted.content == "ctrl-o is available when the agent is idle."
        settle.assert_not_awaited()

    asyncio.run(_test())
