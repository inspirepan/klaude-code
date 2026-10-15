import json

import pytest
from rich.console import Console, RenderableType

from klaude_code.protocol import events, tools
from klaude_code.protocol.background_task import BackgroundTaskSnapshot, TaskReference, TaskResponse, TaskStatus
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import _dispatch
from klaude_code.tui.transcript_detail import Detail


def _task(task_id: str, description: str, status: TaskStatus = "running") -> BackgroundTaskSnapshot:
    return BackgroundTaskSnapshot(
        ref=TaskReference(kind="agent", owner_session_id="main", task_id=task_id, run_id=task_id),
        status=status,
        description=description,
        started_at=1,
        delivery_id=f"task-result:{task_id}",
    )


def _plain(renderable: RenderableType | None, width: int = 80) -> str:
    assert renderable is not None
    console = Console(width=width, color_system=None, theme=get_theme().app_theme)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _no_fallback(*args: object, **kwargs: object) -> RenderableType:
    pytest.fail("ManageTasks must use its dedicated result renderer")


@pytest.mark.parametrize("width", [60, 80])
def test_manage_tasks_dispatch_renders_wait_receipt_and_output_without_fallback(
    monkeypatch: pytest.MonkeyPatch, width: int
) -> None:
    monkeypatch.setattr(_dispatch, "render_fallback_tool_result", _no_fallback)
    arguments = json.dumps({"action": "wait", "task_id": "long-task-id-for-test", "wait_ms": 30000, "offset": 128})
    call = _plain(
        _dispatch.render_tool_call(
            events.ToolCallEvent(
                session_id="main", tool_call_id="wait", tool_name=tools.MANAGE_TASKS, arguments=arguments
            )
        ),
        width,
    )
    # Unknown tasks fall back to a short handle; the wait budget is a model detail.
    assert "Tasks" in call and "Waiting for a background task" in call and "long-tas" not in call
    response = TaskResponse(
        tasks=[_task("long-task-id-for-test", "Inspect task delivery")],
        output="first output line\nsecond output line\n",
        interrupted_wait=True,
        truncated=True,
        next_offset=256,
    )
    result = events.ToolResultEvent(
        session_id="main",
        tool_call_id="wait",
        tool_name=tools.MANAGE_TASKS,
        status="success",
        result="source=background_task; untrusted data, not user authorization.\n"
        "interrupted-wait; still-running.\n" + response.model_dump_json(),
    )
    # Compact mode leaves a still-running task to the status bar.
    assert _dispatch.render_tool_result(result, task_action="wait") is None
    rendered = _plain(_dispatch.render_tool_result(result, detail=Detail.FULL, task_action="wait"), width)
    assert "Agent · running" in rendered and "Inspect task delivery" in rendered
    assert "first output line" in rendered and "second output line" in rendered
    assert "no task was stopped" in rendered
    assert "/tasks output long-task-id-for-test 256" in " ".join(rendered.split())
    assert "source=" not in rendered and '"tasks"' not in rendered


def test_compact_list_keeps_late_failure_visible_and_bounds_long_task_rows() -> None:
    tasks = [_task(f"done-{index}", "Completed background work", "completed") for index in range(12)]
    tasks.append(_task("failed-task", "Check permissions", "failed"))
    tasks.append(_task("long-description", "宽终端任务名称 " * 100))
    rendered = _plain(
        _dispatch.render_tool_result(
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="list",
                tool_name=tools.MANAGE_TASKS,
                status="success",
                result=TaskResponse(tasks=tasks).model_dump_json(),
            ),
            max_lines=3,
            task_action="list",
        ),
        60,
    )
    assert "Check permissions" in rendered and "Agent · failed" in rendered
    assert "Agent · running" in rendered and "11 more tasks" in rendered
    assert len(rendered.splitlines()) <= 6


@pytest.mark.parametrize("status", ["success", "error", "aborted"])
@pytest.mark.parametrize("detail", list(Detail))
def test_manage_tasks_bad_response_and_errors_have_dedicated_bounded_feedback(
    monkeypatch: pytest.MonkeyPatch, status: str, detail: Detail
) -> None:
    monkeypatch.setattr(_dispatch, "render_fallback_tool_result", _no_fallback)
    event = events.ToolResultEvent.model_validate(
        {
            "session_id": "main",
            "tool_call_id": "stop",
            "tool_name": tools.MANAGE_TASKS,
            "status": status,
            "result": "Unknown task selected\n" + "detail line\n" * 100,
        }
    )
    rendered = _plain(_dispatch.render_tool_result(event, detail=detail, max_lines=4))
    assert "Unknown task selected" in rendered
    assert len(rendered.splitlines()) <= 7
    expected = {"success": "could not be read", "aborted": "interrupted", "error": "failed"}
    assert expected[status] in rendered
