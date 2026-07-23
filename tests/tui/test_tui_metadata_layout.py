from rich.console import Console

from klaude_code.protocol import events
from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem, Usage
from klaude_code.tui.components.metadata import render_task_metadata
from klaude_code.tui.components.rich.theme import get_theme


def test_task_metadata_wraps_details_under_identity_column() -> None:
    usage = Usage(
        input_tokens=10300,
        output_tokens=905,
        reasoning_tokens=382,
        context_size=11200,
        context_limit=400000,
        max_tokens=128000,
        throughput_tps=49.9,
        input_cost=0.01,
        output_cost=0.0207,
    )
    metadata = TaskMetadata(
        model_name="gpt-5.3-codex",
        provider="openai/codex",
        usage=usage,
        step_count=1,
        task_duration_s=18,
    )
    event = events.TaskMetadataEvent(session_id="test", metadata=TaskMetadataItem(main_agent=metadata))

    console = Console(width=80, record=True, force_terminal=False)
    console.print(render_task_metadata(event))

    lines = [line.rstrip() for line in console.export_text(styles=False).splitlines()]
    assert len(lines) >= 2
    flattened = " ".join(line.strip() for line in lines)
    assert "18s" in flattened
    assert "49.9 tok/s" in flattened
    assert "1 step" in flattened
    assert not lines[1].startswith("•")

    indent = len(lines[1]) - len(lines[1].lstrip(" "))
    assert indent >= 2


def test_sub_agent_description_shows_before_token_details() -> None:
    event = events.TaskMetadataEvent(
        session_id="test",
        metadata=TaskMetadataItem(
            main_agent=TaskMetadata(model_name="main-model"),
            sub_agent_task_metadata=[
                TaskMetadata(
                    sub_agent_name="research",
                    description="scan repo",
                    model_name="sub-model",
                    usage=Usage(input_tokens=1000, output_tokens=200),
                )
            ],
        ),
    )

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    model_idx = output.find("sub-model")
    description_idx = output.find("scan repo")
    token_idx = output.find("in 1k")

    assert model_idx != -1
    assert description_idx != -1
    assert token_idx != -1
    assert description_idx < model_idx < token_idx


def test_sub_agent_identity_splits_name_and_model_on_narrow_width() -> None:
    event = events.TaskMetadataEvent(
        session_id="test",
        metadata=TaskMetadataItem(
            main_agent=TaskMetadata(model_name="main-model"),
            sub_agent_task_metadata=[
                TaskMetadata(
                    sub_agent_name="finder",
                    description="tool flow scan",
                    model_name="anthropic/claude-haiku-4.5",
                    provider="google/gemini",
                    usage=Usage(input_tokens=1200, output_tokens=300),
                )
            ],
        ),
    )

    console = Console(width=78, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    lines = [line.rstrip() for line in console.export_text(styles=False).splitlines()]

    finder_idx = next(i for i, line in enumerate(lines) if "finder" in line)
    model_idx = next(i for i, line in enumerate(lines) if "anthropic/claude-haiku-4.5" in line)

    assert model_idx == finder_idx + 1


def test_task_metadata_shows_cache_write_tokens() -> None:
    usage = Usage(
        input_tokens=30_000,
        cached_tokens=20_000,
        cache_write_tokens=5_000,
        output_tokens=2_000,
    )
    metadata = TaskMetadata(model_name="claude-sonnet-4-6", usage=usage)
    event = events.TaskMetadataEvent(session_id="test", metadata=TaskMetadataItem(main_agent=metadata))

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    assert "in 5k" in output
    assert "cache 20k" in output
    assert "cache write 5k" in output


def test_task_metadata_hides_empty_zero_cost() -> None:
    metadata = TaskMetadata(
        model_name="claude-sonnet-4-6",
        usage=Usage(input_cost=0.0, output_cost=0.0, cache_read_cost=0.0),
    )
    event = events.TaskMetadataEvent(session_id="test", metadata=TaskMetadataItem(main_agent=metadata))

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    assert "cost" not in output


def _make_sub_agent(description: str, *, input_tokens: int, reasoning_tokens: int = 0) -> TaskMetadata:
    return TaskMetadata(
        sub_agent_name="general-purpose",
        description=description,
        model_name="sub-model",
        provider="prov",
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=2_000 + reasoning_tokens,
            reasoning_tokens=reasoning_tokens,
            input_cost=0.5,
            throughput_tps=50.0,
        ),
        task_duration_s=180,
        step_count=5,
    )


def _multi_sub_agent_event() -> events.TaskMetadataEvent:
    return events.TaskMetadataEvent(
        session_id="test",
        metadata=TaskMetadataItem(
            main_agent=TaskMetadata(model_name="main-model"),
            sub_agent_task_metadata=[
                _make_sub_agent("first task", input_tokens=80_900, reasoning_tokens=3_500),
                _make_sub_agent("second longer task", input_tokens=1_143_400),
            ],
        ),
    )


def test_multiple_sub_agents_align_metric_columns_on_wide_console() -> None:
    console = Console(width=200, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(_multi_sub_agent_event()))
    lines = console.export_text(styles=False).splitlines()

    metric_lines = [line for line in lines if "cost $" in line and "total cost" not in line]
    assert len(metric_lines) == 2
    for line in metric_lines:
        assert " · " not in line

    for marker in ("in ", "out ", "cost $", "tok/s", "steps"):
        positions = {line.find(marker) for line in metric_lines}
        assert len(positions) == 1, f"column {marker!r} not aligned: {metric_lines}"

    identity_lines = [line for line in lines if "sub-model via prov" in line]
    assert len(identity_lines) == 2
    assert len({line.find("sub-model via prov") for line in identity_lines}) == 1


def test_multiple_sub_agents_fall_back_to_flow_style_on_narrow_console() -> None:
    console = Console(width=60, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(_multi_sub_agent_event()))
    output = console.export_text(styles=False)

    assert " · " in output


def test_single_sub_agent_keeps_flow_style() -> None:
    event = events.TaskMetadataEvent(
        session_id="test",
        metadata=TaskMetadataItem(
            main_agent=TaskMetadata(model_name="main-model"),
            sub_agent_task_metadata=[_make_sub_agent("only task", input_tokens=10_000)],
        ),
    )

    console = Console(width=200, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    assert "in 10k · out 2k" in output


def test_task_metadata_keeps_duration_and_steps_inline_without_worked_summary() -> None:
    metadata = TaskMetadata(model_name="claude-sonnet-4-6", step_count=2, task_duration_s=288)
    event = events.TaskMetadataEvent(session_id="test", metadata=TaskMetadataItem(main_agent=metadata))

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    assert "Worked for" not in output
    assert "4m48s" in output
    assert "2 steps" in output
