from rich.console import Console

from klaude_code.protocol import events, model
from klaude_code.tui.components.metadata import render_task_metadata


def test_task_metadata_wraps_details_under_identity_column() -> None:
    usage = model.Usage(
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
    metadata = model.TaskMetadata(
        model_name="gpt-5.3-codex",
        provider="openai/codex",
        usage=usage,
        turn_count=1,
        task_duration_s=18,
    )
    event = events.TaskMetadataEvent(session_id="test", metadata=model.TaskMetadataItem(main_agent=metadata))

    console = Console(width=80, record=True, force_terminal=False)
    console.print(render_task_metadata(event))

    lines = [line.rstrip() for line in console.export_text(styles=False).splitlines()]
    assert len(lines) >= 2
    assert "1 step, 18s" in " ".join(line.strip() for line in lines)
    assert not lines[1].startswith("•")

    indent = len(lines[1]) - len(lines[1].lstrip(" "))
    assert indent > 2
