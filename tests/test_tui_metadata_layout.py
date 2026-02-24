from rich.console import Console

from klaude_code.protocol import events, model
from klaude_code.tui.components.metadata import render_task_metadata
from klaude_code.tui.components.rich.theme import get_theme


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


def test_sub_agent_description_shows_before_token_details() -> None:
    event = events.TaskMetadataEvent(
        session_id="test",
        metadata=model.TaskMetadataItem(
            main_agent=model.TaskMetadata(model_name="main-model"),
            sub_agent_task_metadata=[
                model.TaskMetadata(
                    sub_agent_name="research",
                    description="scan repo",
                    model_name="sub-model",
                    usage=model.Usage(input_tokens=1000, output_tokens=200),
                )
            ],
        ),
    )

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_metadata(event))
    output = console.export_text(styles=False)

    model_idx = output.find("sub-model")
    description_idx = output.find("scan repo")
    token_idx = output.find("input 1k")

    assert model_idx != -1
    assert description_idx != -1
    assert token_idx != -1
    assert model_idx < description_idx < token_idx
    assert "sub-model scan repo, input 1k" in output
