import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.protocol.models import SessionStatsUIExtra, TaskMetadata, Usage
from klaude_code.tui.components.command_output import render_notice, render_session_stats
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme


def test_render_command_output_default_uses_command_output_style() -> None:
    event = events.NoticeEvent(session_id="s1", content="hello")

    rendered = render_notice(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "hello"
    assert rendered.style == ThemeKey.COMMAND_OUTPUT


def test_render_command_output_default_error_uses_error_style() -> None:
    event = events.NoticeEvent(session_id="s1", content="oops", is_error=True)

    rendered = render_notice(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "oops"
    assert rendered.style == ThemeKey.ERROR


def _stats(**updates: object) -> SessionStatsUIExtra:
    data: dict[str, object] = {
        "events_file_path": "/very/long/session/directory/" + "nested/" * 12 + "events.jsonl",
        "session_id": "session-" + "a" * 64,
        "user_messages_count": 2,
        "assistant_messages_count": 4,
        "tool_calls_count": 3,
        "tool_results_count": 3,
        "total_messages_count": 9,
        "usage": Usage(),
        "task_count": 7,
    }
    data.update(updates)
    return SessionStatsUIExtra.model_validate(data)


def _render_stats(stats: SessionStatsUIExtra, width: int) -> str:
    console = Console(width=width, record=True, theme=get_theme().app_theme)
    console.print(render_session_stats(events.SessionStatsEvent(session_id="s1", stats=stats)))
    output = console.export_text()
    assert all(cell_len(line) <= width for line in output.splitlines())
    return output


@pytest.mark.parametrize("width", [80, 40])
def test_session_stats_usage_tree_wraps_and_preserves_individual_runs(width: int) -> None:
    main = TaskMetadata(
        model_name="shared-model",
        usage=Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            cache_write_tokens=5_000,
            output_tokens=2_000,
            reasoning_tokens=500,
            input_cost=1,
        ),
    )
    child = TaskMetadata(
        model_name="child-model",
        sub_agent_name="finder",
        description="scan tools",
        usage=Usage(input_tokens=100, output_tokens=50, input_cost=2, currency="CNY"),
        step_count=3,
    )
    other = child.model_copy(update={"description": "scan UI"})
    stats = _stats(
        main_agent_by_model=[main],
        sub_agent_runs=[child, other],
        by_model=TaskMetadata.aggregate_by_model([main, child, other]),
    )

    output = _render_stats(stats, width)
    flat = " ".join(output.split())

    assert "USD 1.0000" in output and "CNY 4.0000" in output
    assert "Main agent" in output and "Sub-agents · 2 runs" in output
    assert output.count("finder") == 2
    assert "scan tools" in output and "scan UI" in output
    assert "in 5k" in flat and "out 1.5k" in flat
    assert "cache 20k" in flat and "cache write 5k" in flat and "thought 500" in flat
    assert "Messages  2 user" in output and "3 calls" in output
    assert "running usage excluded" in flat
    assert "Session " in output and "Events " in output
    assert "Usage by model" not in output and "7 tasks" not in output


@pytest.mark.parametrize("width", [80, 40])
def test_session_stats_empty_state(width: int) -> None:
    output = _render_stats(_stats(), width)

    assert "Total cost  unavailable" in output
    assert "No settled usage" in output and "No settled runs" in output


def test_session_stats_legacy_does_not_invent_agent_attribution() -> None:
    meta = TaskMetadata(model_name="old-model", usage=Usage(input_tokens=10, input_cost=1))

    output = _render_stats(_stats(by_model=[meta]), 80)

    assert "Agent attribution unavailable (legacy)" in output
    assert "old-model" in output and "USD 1.0000" in output
    assert "Main agent" not in output


def test_session_stats_missing_child_usage_is_explicit() -> None:
    child = TaskMetadata(sub_agent_name="finder", description="scan repo", model_name="unknown")

    output = _render_stats(_stats(sub_agent_runs=[child]), 40)

    assert "scan repo" in output and "Usage unavailable" in output


def test_session_stats_legacy_total_without_model_breakdown() -> None:
    output = _render_stats(_stats(usage=Usage(input_tokens=100, input_cost=1, currency="EUR")), 80)

    assert "Agent attribution unavailable (legacy)" in output
    assert "All agents" in output and "cost EUR 1.0000" in output
    assert "Total cost  EUR 1.0000" in output
    assert "No settled usage" not in output
