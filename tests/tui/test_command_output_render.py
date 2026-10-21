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
    rendered = render_session_stats(events.SessionStatsEvent(session_id="s1", stats=stats))
    assert all(not segment.style or not segment.style.bold for segment in console.render(rendered))
    console.print(rendered)
    output = console.export_text()
    assert all(cell_len(line) <= width for line in output.splitlines())
    return output


@pytest.mark.parametrize("width", [80, 40])
def test_session_stats_usage_list_wraps_and_preserves_individual_runs(width: int) -> None:
    main = TaskMetadata(
        model_name="shared-model",
        usage=Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            cache_write_tokens=5_000,
            output_tokens=2_000,
            reasoning_tokens=500,
            input_cost=1,
            context_size=1000,
            context_limit=10000,
            max_tokens=1000,
            throughput_tps=23.9,
        ),
        task_duration_s=1795,
        step_count=49,
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
    assert "ctx 1k/9k (11.1%)" in flat and "29m55s" in flat
    assert "23.9 tok/s" in flat and "49 steps" in flat
    child_lines = output[output.index("scan tools") : output.index("scan UI")].splitlines()
    assert all(line.strip() for line in child_lines)
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
    assert "All agents" in output and "EUR 1.0000" in output
    assert "Total cost  EUR 1.0000" in output
    assert "No settled usage" not in output


@pytest.mark.parametrize("width", [40, 80, 160])
def test_session_stats_cost_first_sorting_preserves_metrics_and_unknowns(width: int) -> None:
    cheap = TaskMetadata(
        model_name="model",
        provider="chatgpt",
        sub_agent_name="finder",
        description="cheap run",
        usage=Usage(
            input_tokens=1000,
            cached_tokens=200,
            cache_write_tokens=100,
            output_tokens=100,
            reasoning_tokens=20,
            input_cost=0.001,
            context_size=1000,
            context_limit=10000,
            max_tokens=1000,
            throughput_tps=12.5,
        ),
        task_duration_s=65,
        step_count=3,
    )
    expensive = cheap.model_copy(update={"description": "expensive run", "usage": Usage(input_cost=2)})
    free = cheap.model_copy(update={"description": "free run", "usage": Usage(input_tokens=1, input_cost=0)})
    unknown = cheap.model_copy(update={"description": "unknown run", "usage": None})
    runs = [cheap, unknown, free, expensive]

    output = _render_stats(_stats(sub_agent_runs=runs), width)
    flat = " ".join(output.split())

    assert output.index("expensive run") < output.index("cheap run") < output.index("free run")
    assert output.index("free run") < output.index("unknown run")
    for cost, description in [("$2.0000", "expensive run"), ("$0.0010", "cheap run"), ("$0.0000", "free run")]:
        assert any(cost in line and description in line for line in output.splitlines())
    assert "1 unknown" in flat
    for metric in [
        "in 700",
        "cache 200",
        "cache write 100",
        "out 80",
        "thought 20",
        "ctx 1k/9k",
        "12.5 tok/s",
        "3 steps",
    ]:
        assert metric in flat
    assert "1m05s" in flat
    assert "via chatgpt" in flat
    assert runs == [cheap, unknown, free, expensive]


def test_session_stats_narrow_details_do_not_truncate_paths_or_models() -> None:
    path = "src/klaude_code/tui/components/command_output.py"
    model = "provider/very-long-model-name-with-reasoning"
    run = TaskMetadata(description=f"Review {path}", model_name=model, usage=Usage(input_cost=1))

    output = _render_stats(_stats(sub_agent_runs=[run]), 40)
    compact = "".join(output.split())

    assert path in compact
    assert model in compact
