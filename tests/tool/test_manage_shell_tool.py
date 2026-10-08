from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from klaude_code.protocol.models import ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskOutput, ShellTaskSnapshot
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.shell.manage_shell_tool import ManageShellTool
from klaude_code.tool.shell.task_manager import ShellTaskManager


def _context(tmp_path: Path, manager: ShellTaskManager | None, session_id: str = "owner") -> ToolContext:
    return ToolContext(
        file_tracker={},
        todo_context=TodoContext(lambda: [], lambda _: None),
        session_id=session_id,
        work_dir=tmp_path,
        shell_task_manager=manager,
    )


@pytest.fixture
def task() -> ShellTaskSnapshot:
    return ShellTaskSnapshot(
        task_id="0123456789abcdef0123456789abcdef",
        session_id="owner",
        command="echo command\n  fallback",
        description="Build\n  package",
        work_dir="/private/work-dir",
        status="running",
        background=True,
        started_at=1234.5,
        output_path="/private/output.log",
        pid=99887,
    )


@pytest.mark.parametrize("action", ["list", "output", "wait", "stop"])
@pytest.mark.parametrize("status", ["running", "stopping", "completed", "failed", "stopped", "timed_out", "lost"])
def test_actions_preserve_ui_snapshot_and_report_process_status(
    tmp_path: Path, task: ShellTaskSnapshot, action: str, status: str
) -> None:
    task = ShellTaskSnapshot.model_validate(
        task.model_dump() | {"status": status, "exit_code": None if status in ("running", "stopping", "lost") else 7}
    )
    manager = MagicMock(spec=ShellTaskManager)
    manager.list_tasks = AsyncMock(return_value=[task])
    manager.read_output = AsyncMock(
        return_value=ShellTaskOutput(task=task, output="  indented\n", next_offset=11, truncated=True)
    )
    manager.wait_task = AsyncMock(return_value=task)
    manager.stop_task = AsyncMock(return_value=task)

    result = asyncio.run(
        ManageShellTool.call(json.dumps({"action": action, "task_id": task.task_id}), _context(tmp_path, manager))
    )

    assert result.status == "success"
    assert isinstance(result.ui_extra, ShellTaskUIExtra)
    assert result.ui_extra.action == action
    assert result.ui_extra.tasks == [task]
    expected_status = status + (", exit 7" if task.exit_code is not None else "")
    assert result.output_text.startswith(f"Task {task.task_id} [{expected_status}]: Build package")
    for value in (task.work_dir, task.output_path, str(task.pid), str(task.started_at), "session_id", "background"):
        assert value not in result.output_text
    if status == "lost":
        assert "not a successful completion" in result.output_text
    if action == "output":
        assert result.output_text.endswith("Output:\n  indented\n")
        assert "next_offset=11; truncated=true" in result.output_text
        assert result.ui_extra.output == "  indented\n"
        assert result.ui_extra.next_offset == 11
        assert result.ui_extra.truncated
        manager.read_output.assert_awaited_once_with("owner", task.task_id, offset=0, limit=16384)
    else:
        assert "indented" not in result.output_text
        assert result.ui_extra.output is None
        manager.read_output.assert_not_awaited()
        if action == "wait":
            manager.wait_task.assert_awaited_once_with("owner", task.task_id, wait_ms=10000)
        elif action == "stop":
            manager.stop_task.assert_awaited_once_with("owner", task.task_id)


def test_list_empty(tmp_path: Path) -> None:
    manager = MagicMock(spec=ShellTaskManager)
    manager.list_tasks = AsyncMock(return_value=[])
    result = asyncio.run(ManageShellTool.call('{"action":"list"}', _context(tmp_path, manager)))
    assert result.status == "success"
    assert result.output_text == "No background shell tasks."
    assert result.ui_extra == ShellTaskUIExtra(action="list", tasks=[])
    manager.list_tasks.assert_awaited_once_with("owner", work_dir=tmp_path)


def test_list_command_fallback_reason_and_expired_output(tmp_path: Path, task: ShellTaskSnapshot) -> None:
    task = task.model_copy(update={"description": " \n ", "reason": "output quota\n exceeded", "output_expired": True})
    manager = MagicMock(spec=ShellTaskManager)
    manager.list_tasks = AsyncMock(return_value=[task, task.model_copy(update={"task_id": "second"})])
    result = asyncio.run(ManageShellTool.call('{"action":"list"}', _context(tmp_path, manager)))
    assert result.output_text.splitlines() == [
        f"Task {task.task_id} [running]: echo command fallback; output quota exceeded; output expired",
        "Task second [running]: echo command fallback; output quota exceeded; output expired",
    ]


@pytest.mark.parametrize("arguments", ['{"action":"wait"}', '{"action":"invalid"}', "not-json"])
def test_invalid_arguments_have_no_ui_extra(tmp_path: Path, arguments: str) -> None:
    manager = MagicMock(spec=ShellTaskManager)
    manager.list_tasks = AsyncMock(return_value=[])
    result = asyncio.run(ManageShellTool.call(arguments, _context(tmp_path, manager)))
    assert result.status == "error"
    assert result.ui_extra is None


def test_missing_manager_has_no_ui_extra(tmp_path: Path) -> None:
    result = asyncio.run(ManageShellTool.call('{"action":"list"}', _context(tmp_path, None)))
    assert result.status == "error"
    assert result.ui_extra is None


@pytest.mark.parametrize("error", [ValueError("unknown task"), OSError("output unavailable")])
def test_manager_error_has_no_ui_extra(tmp_path: Path, error: Exception) -> None:
    manager = MagicMock(spec=ShellTaskManager)
    manager.list_tasks = AsyncMock(return_value=[])
    manager.read_output = AsyncMock(side_effect=error)
    result = asyncio.run(ManageShellTool.call('{"action":"output","task_id":"missing"}', _context(tmp_path, manager)))
    assert result.status == "error"
    assert result.output_text == f"ManageShell error: {error}"
    assert result.ui_extra is None


def test_real_output_pagination_and_session_isolation(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            task = await manager.start(
                session_id="owner",
                work_dir=tmp_path,
                command="printf '  abcdef'",
                description="Read indented output",
                timeout_ms=None,
                env=os.environ.copy(),
                background=True,
            )
            await manager.wait_task("owner", task.task_id, wait_ms=3000)
            context = _context(tmp_path, manager)
            chunks: list[str] = []
            for offset, expected, truncated in [(0, "  ab", True), (4, "cdef", False), (8, "", False)]:
                result = await ManageShellTool.call(
                    json.dumps({"action": "output", "task_id": task.task_id, "offset": offset, "limit": 4}), context
                )
                assert result.status == "success"
                assert isinstance(result.ui_extra, ShellTaskUIExtra)
                assert result.ui_extra.output is not None
                assert result.ui_extra.output == expected
                assert result.ui_extra.next_offset == min(offset + 4, 8)
                assert result.ui_extra.truncated == truncated
                assert f"next_offset={min(offset + 4, 8)}; truncated={str(truncated).lower()}" in result.output_text
                if expected:
                    assert result.output_text.endswith(f"Output:\n{expected}")
                else:
                    assert result.output_text.endswith("No output available.")
                chunks.append(result.ui_extra.output)
            assert "".join(chunks) == "  abcdef"
            other_context = _context(tmp_path, manager, "other")
            listed = await ManageShellTool.call('{"action":"list"}', other_context)
            assert listed.ui_extra == ShellTaskUIExtra(action="list", tasks=[])
            for action in ("output", "wait", "stop"):
                result = await ManageShellTool.call(
                    json.dumps({"action": action, "task_id": task.task_id}), other_context
                )
                assert result.status == "error"
                assert result.ui_extra is None
            assert (await manager.wait_task("owner", task.task_id, wait_ms=0)).status == "completed"
        finally:
            await manager.aclose()

    asyncio.run(run())
