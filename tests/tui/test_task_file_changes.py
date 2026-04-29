from rich.console import Console

from klaude_code.protocol import events, message
from klaude_code.protocol.models import TaskFileChange
from klaude_code.tui.commands import RenderTaskFileChangeSummary
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.task_file_changes import render_task_file_change_summary
from klaude_code.tui.machine import DisplayStateMachine


def test_task_file_change_summary_event_renders_command() -> None:
    machine = DisplayStateMachine()
    event = events.TaskFileChangeSummaryEvent(
        session_id="s1",
        summary=message.TaskFileChangeSummaryEntry(
            files=[TaskFileChange(path="src/app.py", added=2, removed=1, edited=True)]
        ),
    )

    commands = machine.transition(event)

    assert any(isinstance(command, RenderTaskFileChangeSummary) for command in commands)


def test_task_file_change_summary_render_includes_diff_stat() -> None:
    event = events.TaskFileChangeSummaryEvent(
        session_id="s1",
        summary=message.TaskFileChangeSummaryEntry(
            files=[
                TaskFileChange(path="src/app.py", added=2, removed=1, edited=True),
                TaskFileChange(path="tests/test_app.py", added=4, removed=0, created=True),
                TaskFileChange(path="src/removed.py", added=0, removed=3, deleted=True),
            ]
        ),
    )

    console = Console(width=100, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_task_file_change_summary(event))
    output = console.export_text(styles=False)
    lines = output.splitlines()

    assert lines[0].strip() == ""
    assert lines[1].strip() == "FILE CHANGES · 3 files"
    assert lines[-1].strip() == ""
    assert {len(line) for line in lines} == {28}
    assert "FILE CHANGES · 3 files" in output
    assert "• 2 files changed" not in output
    assert "6 insertions(+)" not in output
    assert "1 deletion(-)" not in output
    assert "src/app.py" in output
    assert "~ ./src/app.py" in output
    assert "+2 -1" in output
    assert "tests/test_app.py" in output
    assert "+ ./tests/test_app.py" in output
    assert "+4" in output
    assert "src/removed.py" in output
    assert "- ./src/removed.py" in output
    assert "-3" in output
