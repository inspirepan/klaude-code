from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
import sys
import threading
import weakref
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.shell.bash_tool import BashTool
from klaude_code.tool.shell.manage_shell_tool import ManageShellTool
from klaude_code.tool.shell.task_manager import ShellTaskManager


def _context(work_dir: Path, manager: ShellTaskManager | None, session_id: str = "test") -> ToolContext:
    return ToolContext(
        file_tracker={},
        todo_context=TodoContext(lambda: [], lambda _: None),
        session_id=session_id,
        work_dir=work_dir,
        shell_task_manager=manager,
    )


async def _start(
    manager: ShellTaskManager,
    work_dir: Path,
    command: str,
    *,
    timeout_ms: int | None = None,
    background: bool = True,
    session_id: str = "test",
) -> ShellTaskSnapshot:
    return await manager.start(
        session_id=session_id,
        work_dir=work_dir,
        command=command,
        description="test",
        timeout_ms=timeout_ms,
        env=os.environ.copy(),
        background=background,
    )


def test_handoff_keeps_pid_and_executes_once(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            result = await BashTool.call_with_args(
                BashTool.BashArguments(command="echo $$; echo once >> calls; sleep 0.2; echo $$", wait_ms=20),
                _context(tmp_path, manager),
            )
            tasks = await manager.list_tasks("test")
            assert len(tasks) == 1 and tasks[0].task_id in result.output_text
            assert (await manager.wait_task("test", tasks[0].task_id, wait_ms=3000)).status == "completed"
            output = await manager.read_output("test", tasks[0].task_id)
            assert output.output.splitlines() == [str(tasks[0].pid)] * 2
            assert (tmp_path / "calls").read_text() == "once\n"
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_incremental_output_handles_split_utf8(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            task = await _start(
                manager, tmp_path, "printf '\\344'; sleep 0.1; printf '\\275\\240abc'; sleep 0.1; printf done"
            )
            await asyncio.sleep(0.06)
            first = await manager.read_output("test", task.task_id, limit=1)
            assert first.output == "" and first.next_offset == 0
            await manager.wait_task("test", task.task_id, wait_ms=3000)
            offset = 0
            chunks: list[str] = []
            while True:
                page = await manager.read_output("test", task.task_id, offset=offset, limit=1)
                chunks.append(page.output)
                offset = page.next_offset
                if not page.truncated:
                    break
            assert "".join(chunks) == "\u4f60abcdone"
            assert offset == len("\u4f60abcdone".encode())
            with pytest.raises(ValueError):
                await manager.read_output("test", task.task_id, offset=-1)
            with pytest.raises(ValueError):
                await manager.read_output("test", task.task_id, limit=-1)
        finally:
            await manager.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("stop", [False, True])
def test_hard_timeout_and_stop_kill_descendants(tmp_path: Path, isolated_home: Path, stop: bool) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            task = await _start(
                manager,
                tmp_path,
                "(sleep 1.5; echo leaked > leaked) & echo partial; wait",
                timeout_ms=None if stop else 80,
            )
            if stop:
                await asyncio.sleep(0.04)
                done = await manager.stop_task("test", task.task_id)
            else:
                done = await manager.wait_task("test", task.task_id, wait_ms=3000)
            assert done.status == ("stopped" if stop else "timed_out")
            assert "partial" in (await manager.read_output("test", task.task_id)).output
            await asyncio.sleep(0.5)
            assert not (tmp_path / "leaked").exists()
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_wait_timeout_session_isolation_and_manage_tool(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            task = await _start(manager, tmp_path, "sleep 0.2; echo done")
            assert (await manager.wait_task("test", task.task_id, wait_ms=1)).status == "running"
            assert manager.active_session_ids() == {"test"}
            assert await manager.list_tasks("other") == []
            for operation in (manager.read_output, manager.stop_task, manager.wait_task):
                with pytest.raises(ValueError):
                    await operation("other", task.task_id)
            result = await ManageShellTool.call(
                json.dumps({"action": "output", "task_id": task.task_id}), _context(tmp_path, manager, "other")
            )
            assert result.status == "error"
            assert (await manager.wait_task("test", task.task_id, wait_ms=3000)).status == "completed"
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_completion_detach_race_notifies_once_and_never_foreground(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        notifications: list[str] = []
        updates: list[list[ShellTaskSnapshot]] = []

        async def complete(task: ShellTaskSnapshot) -> None:
            notifications.append(task.task_id)

        async def update(_: str, tasks: list[ShellTaskSnapshot]) -> None:
            updates.append(tasks)
            await asyncio.sleep(0)

        manager = ShellTaskManager(on_update=update, on_complete=complete)
        try:
            foreground = await _start(manager, tmp_path, "true", background=False)
            await manager.wait_task("test", foreground.task_id, wait_ms=3000)
            assert not notifications
            await asyncio.gather(*(manager.background_task("test", foreground.task_id) for _ in range(3)))
            assert notifications == [foreground.task_id]
            racing = await _start(manager, tmp_path, "sleep 0.03", background=False)
            await asyncio.gather(
                manager.background_task("test", racing.task_id), manager.wait_task("test", racing.task_id, wait_ms=3000)
            )
            await asyncio.sleep(0)
            assert notifications.count(racing.task_id) == 1
            assert updates[-1][-1].status == "completed"
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_restart_marks_active_lost_without_using_pid(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        task = await _start(manager, tmp_path, "echo preserved")
        await manager.wait_task("test", task.task_id, wait_ms=3000)
        await manager.aclose()
        metadata = Path(task.output_path).with_suffix(".json")
        data = json.loads(metadata.read_text())
        data.update(status="running", pid=os.getpid(), ended_at=None)
        metadata.write_text(json.dumps(data))
        restored = ShellTaskManager()
        tasks = await restored.list_tasks("test", work_dir=tmp_path)
        assert tasks[0].status == "lost"
        assert (await restored.stop_task("test", task.task_id)).status == "lost"
        assert "preserved" in (await restored.read_output("test", task.task_id)).output
        assert json.loads(metadata.read_text())["status"] == "lost"
        await restored.aclose()

    asyncio.run(run())


def test_output_quota_and_retention(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager(max_output_bytes=128, max_completed_per_session=1)
        try:
            first = await _start(manager, tmp_path, "printf '%1000s' x; sleep 10")
            done = await manager.wait_task("test", first.task_id, wait_ms=3000)
            assert done.status == "failed" and done.reason and "quota" in done.reason
            assert Path(first.output_path).stat().st_size <= 128
            second = await _start(manager, tmp_path, "echo retained")
            await manager.wait_task("test", second.task_id, wait_ms=3000)
            assert not Path(first.output_path).exists()
            assert Path(first.output_path).with_suffix(".json").exists()
            assert len(await manager.list_tasks("test")) == 1
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_direct_calls_wait_and_explicit_background_requires_manager(tmp_path: Path) -> None:
    async def run() -> None:
        result = await BashTool.call_with_args(
            BashTool.BashArguments(command="sleep 0.05; echo done", wait_ms=0), _context(tmp_path, None)
        )
        assert result.output_text == "done"
        result = await BashTool.call_with_args(
            BashTool.BashArguments(command="echo forbidden > forbidden", run_in_background=True),
            _context(tmp_path, None),
        )
        assert result.status == "error" and not (tmp_path / "forbidden").exists()

    asyncio.run(run())


def test_shell_background_does_not_wait_for_inherited_fds(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            task = await _start(manager, tmp_path, "sleep 20 & echo finished")
            assert (await manager.wait_task("test", task.task_id, wait_ms=3000)).status == "completed"
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_cancel_after_detach_does_not_kill_background(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        detached = asyncio.Event()
        hold_callback = asyncio.Event()

        async def update(_: str, tasks: list[ShellTaskSnapshot]) -> None:
            if tasks and tasks[0].status == "running":
                detached.set()
                await hold_callback.wait()

        manager = ShellTaskManager(on_update=update)
        call = asyncio.create_task(
            BashTool.call_with_args(
                BashTool.BashArguments(command="sleep 0.2; echo survived", run_in_background=True),
                _context(tmp_path, manager),
            )
        )
        try:
            await asyncio.wait_for(detached.wait(), 2)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            tasks = await manager.list_tasks("test")
            assert tasks[0].status == "running"
            hold_callback.set()
            assert (await manager.wait_task("test", tasks[0].task_id, wait_ms=3000)).status == "completed"
            assert "survived" in (await manager.read_output("test", tasks[0].task_id)).output
        finally:
            hold_callback.set()
            await manager.aclose()

    asyncio.run(run())


def test_running_limit_and_foreground_file_tracking(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager(max_running_per_session=1)
        try:
            first = await _start(manager, tmp_path, "sleep 0.2")
            with pytest.raises(ValueError, match="limit"):
                await _start(manager, tmp_path, "true")
            await manager.wait_task("test", first.task_id, wait_ms=3000)
            (tmp_path / "read.txt").write_text("tracked\n")
            context = _context(tmp_path, manager)
            result = await BashTool.call_with_args(BashTool.BashArguments(command="cat read.txt"), context)
            assert result.output_text == "tracked"
            assert str(tmp_path / "read.txt") in context.file_tracker
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_automatic_handoff_preserves_explicit_hard_timeout(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        try:
            result = await BashTool.call_with_args(
                BashTool.BashArguments(command="sleep 20", wait_ms=10, timeout_ms=60), _context(tmp_path, manager)
            )
            task = (await manager.list_tasks("test"))[0]
            assert task.task_id in result.output_text
            done = await manager.wait_task("test", task.task_id, wait_ms=3000)
            assert done.status == "timed_out" and done.reason and "60 ms" in done.reason
            assert BashTool.BashArguments.model_validate_json('{"command":"true","timeout_ms":null}').timeout_ms is None
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_recovery_ignores_untrusted_paths_and_task_ids(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        task = await _start(manager, tmp_path, "echo own-output")
        await manager.wait_task("test", task.task_id, wait_ms=3000)
        await manager.aclose()
        output_path = Path(task.output_path)
        metadata = output_path.with_suffix(".json")
        external = tmp_path / "external.log"
        external.write_text("outside-session")
        data = json.loads(metadata.read_text())
        data["output_path"] = str(external)
        metadata.write_text(json.dumps(data))
        malicious = dict(data, task_id="../../external", session_id="test")
        (metadata.parent / "malicious.json").write_text(json.dumps(malicious))
        restored = ShellTaskManager()
        try:
            tasks = await restored.list_tasks("test", work_dir=tmp_path)
            assert len(tasks) == 1 and tasks[0].output_path == str(output_path)
            assert (await restored.read_output("test", task.task_id)).output == "own-output\n"
            if os.name == "posix":
                saved = output_path.with_suffix(".saved")
                output_path.rename(saved)
                output_path.symlink_to(external)
                with pytest.raises(OSError):
                    await restored.read_output("test", task.task_id)
                assert external.read_text() == "outside-session"
        finally:
            await restored.aclose()

    asyncio.run(run())


def test_close_stops_background_without_notifying_model(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        completions: list[ShellTaskSnapshot] = []
        updates: list[list[ShellTaskSnapshot]] = []

        async def complete(task: ShellTaskSnapshot) -> None:
            completions.append(task)

        async def update(_: str, tasks: list[ShellTaskSnapshot]) -> None:
            updates.append(tasks)

        manager = ShellTaskManager(on_complete=complete, on_update=update)
        task = await _start(manager, tmp_path, "sleep 20")
        updates.clear()
        await manager.aclose()
        assert not manager.has_running_tasks()
        assert not completions and not updates
        assert (await manager.wait_task("test", task.task_id, wait_ms=0)).status == "stopped"
        assert json.loads(Path(task.output_path).with_suffix(".json").read_text())["status"] == "stopped"

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="setsid requires POSIX")
@pytest.mark.parametrize("action", ["timeout", "stop", "close", "natural"])
def test_escaped_output_writer_cannot_block_task_cleanup(tmp_path: Path, isolated_home: Path, action: str) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        script = """
import os, time
from pathlib import Path
reader, writer = os.pipe()
if os.fork():
    os.close(writer)
    os.read(reader, 1)
    os._exit(0)
os.close(reader)
os.setsid()
Path('escaped.pid').write_text(str(os.getpid()))
print('escaped-ready', flush=True)
os.write(writer, b'1')
time.sleep(20)
"""
        try:
            task = await _start(
                manager,
                tmp_path,
                f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}",
                timeout_ms=80 if action == "timeout" else None,
            )
            process = manager._get("test", task.task_id).process
            assert process is not None

            async def leader_exited() -> None:
                while process.returncode is None:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(leader_exited(), 2)
            if action == "stop":
                done = await asyncio.wait_for(manager.stop_task("test", task.task_id), 0.6)
                assert done.status == "stopped"
            elif action == "close":
                await asyncio.wait_for(manager.aclose(), 0.6)
                assert (await manager.wait_task("test", task.task_id, wait_ms=0)).status == "stopped"
            elif action == "timeout":
                done = await manager.wait_task("test", task.task_id, wait_ms=600)
                assert done.status == "timed_out"
            else:
                done = await manager.wait_task("test", task.task_id, wait_ms=2500)
                assert done.status == "failed" and done.reason and "escaped descendants" in done.reason
            assert not manager.has_running_tasks()
            assert "escaped-ready" in (await manager.read_output("test", task.task_id)).output
            # The manager must not claim ownership of or kill this escaped PID.
            os.kill(int((tmp_path / "escaped.pid").read_text()), 0)
        finally:
            pid_file = tmp_path / "escaped.pid"
            if pid_file.exists():
                with contextlib.suppress(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
            await manager.aclose()

    asyncio.run(run())


def test_close_waits_for_inflight_spawn_before_stopping_tasks(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        spawned = asyncio.Event()
        release = asyncio.Event()
        original = asyncio.create_subprocess_exec

        async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
            process = await original(*args, **kwargs)
            spawned.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        starting = asyncio.create_task(_start(manager, tmp_path, "sleep 20"))
        closing: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(spawned.wait(), 2)
            closing = asyncio.create_task(manager.aclose())
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            task = await asyncio.wait_for(starting, 2)
            await asyncio.wait_for(closing, 3)
            assert not manager.has_running_tasks()
            assert (await manager.wait_task("test", task.task_id, wait_ms=0)).status == "stopped"
            with pytest.raises(ValueError, match="closed"):
                await _start(manager, tmp_path, "true")
        finally:
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())


def test_cancelled_inflight_spawn_keeps_process_owned(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        spawned = asyncio.Event()
        release = asyncio.Event()
        original = asyncio.create_subprocess_exec

        async def spawn(*args: str, **kwargs: Any) -> asyncio.subprocess.Process:
            process = await original(*args, **kwargs)
            spawned.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        starting = asyncio.create_task(_start(manager, tmp_path, "sleep 20"))
        try:
            await asyncio.wait_for(spawned.wait(), 2)
            starting.cancel()
            await asyncio.sleep(0)
            assert not starting.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(starting, 3)
            task = (await manager.list_tasks("test"))[0]
            assert task.status == "stopped"
            assert not manager.has_running_tasks()
        finally:
            release.set()
            await asyncio.gather(starting, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["fsync", "persist", "prune"])
def test_storage_failure_publishes_final_state_and_releases_tracker(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    del isolated_home

    class Capture:
        pass

    async def run() -> None:
        completions: list[ShellTaskSnapshot] = []
        updates: list[list[ShellTaskSnapshot]] = []
        notified = asyncio.Event()

        async def complete(task: ShellTaskSnapshot) -> None:
            completions.append(task)
            notified.set()

        async def update(_: str, tasks: list[ShellTaskSnapshot]) -> None:
            updates.append(tasks)

        manager = ShellTaskManager(on_complete=complete, on_update=update)
        capture = Capture()
        reference = weakref.ref(capture)
        try:
            task = await manager.start(
                session_id="test",
                work_dir=tmp_path,
                command="sleep 0.15; echo done",
                description="test",
                timeout_ms=None,
                env=os.environ.copy(),
                background=True,
                on_success=lambda held=capture: None,
            )
            del capture

            def fail_sync(*_: object) -> None:
                raise OSError(f"injected {failure} failure")

            async def fail_prune(_: str, *, reserve: int = 0) -> None:
                del reserve
                raise OSError("injected prune failure")

            if failure == "fsync":
                monkeypatch.setattr(manager, "_sync_output", fail_sync)
            elif failure == "persist":
                monkeypatch.setattr(manager, "_write_snapshot", fail_sync)
            else:
                monkeypatch.setattr(manager, "_prune", fail_prune)
            done = await manager.wait_task("test", task.task_id, wait_ms=3000)
            await asyncio.wait_for(notified.wait(), 2)
            assert done.status == "failed" and done.reason and f"injected {failure}" in done.reason
            assert len(completions) == 1 and completions[0].status == "failed"
            assert updates[-1][0].status == "failed"
            assert manager._get("test", task.task_id).on_success is None
            assert reference() is None
        finally:
            await manager.aclose()

    asyncio.run(run())


def test_metadata_writer_is_responsive_immutable_and_cancel_safe(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        release = threading.Event()
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        writes: list[dict[str, object]] = []
        original = manager._write_snapshot
        first = True

        def write(directory: Path, task_id: str, payload: str) -> None:
            nonlocal first
            if first:
                first = False
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise TimeoutError("test writer gate was not released")
            writes.append(json.loads(payload))
            original(directory, task_id, payload)

        background: asyncio.Task[ShellTaskSnapshot] | None = None
        stopping: asyncio.Task[ShellTaskSnapshot] | None = None
        try:
            task = await _start(manager, tmp_path, "sleep 20", background=False)
            monkeypatch.setattr(manager, "_write_snapshot", write)
            background = asyncio.create_task(manager.background_task("test", task.task_id))
            await asyncio.wait_for(entered.wait(), 2)
            manager._get("test", task.task_id).snapshot.description = "changed while writing"
            background.cancel()
            stopping = asyncio.create_task(manager.stop_task("test", task.task_id))
            await asyncio.sleep(0.02)
            assert not background.done() and not stopping.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await background
            assert (await asyncio.wait_for(stopping, 3)).status == "stopped"
            assert writes[0]["description"] == "test"
            assert [item["status"] for item in writes] == ["running", "stopping", "stopped"]
            assert json.loads(Path(task.output_path).with_suffix(".json").read_text())["status"] == "stopped"
        finally:
            release.set()
            for pending in (background, stopping):
                if pending is not None:
                    await asyncio.gather(pending, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())


def test_cancelled_detach_still_notifies_already_completed_task(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        completions: list[ShellTaskSnapshot] = []
        persisted = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        async def complete(task: ShellTaskSnapshot) -> None:
            completions.append(task)

        manager = ShellTaskManager(on_complete=complete)
        original = manager._write_snapshot

        def write(directory: Path, task_id: str, payload: str) -> None:
            loop.call_soon_threadsafe(persisted.set)
            if not release.wait(5):
                raise TimeoutError("test detach gate was not released")
            original(directory, task_id, payload)

        background: asyncio.Task[ShellTaskSnapshot] | None = None
        try:
            task = await _start(manager, tmp_path, "true", background=False)
            await manager.wait_task("test", task.task_id, wait_ms=3000)
            assert not completions
            monkeypatch.setattr(manager, "_write_snapshot", write)
            background = asyncio.create_task(manager.background_task("test", task.task_id))
            await asyncio.wait_for(persisted.wait(), 2)
            background.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await background
            assert len(completions) == 1 and completions[0].task_id == task.task_id
        finally:
            release.set()
            if background is not None:
                await asyncio.gather(background, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())


def test_bash_waits_for_final_storage_outcome_before_returning_success(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager()
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def sync_output(_: Path, __: str) -> None:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("test fsync gate was not released")
            raise OSError("injected delayed fsync failure")

        monkeypatch.setattr(manager, "_sync_output", sync_output)
        call = asyncio.create_task(
            BashTool.call_with_args(BashTool.BashArguments(command="printf important"), _context(tmp_path, manager))
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task = next(iter(manager._tasks.values()))
            assert not task.done.is_set()
            await asyncio.sleep(0.15)
            assert not call.done()
            snapshot = await manager.wait_task("test", task.snapshot.task_id, wait_ms=1)
            assert snapshot.status == "running" and snapshot.exit_code is None and snapshot.ended_at is None
            assert manager.has_running_tasks()
            assert (await manager.read_output("test", task.snapshot.task_id)).task.status == "running"
            release.set()
            result = await asyncio.wait_for(call, 3)
            assert result.status == "error" and "delayed fsync failure" in result.output_text
            assert "important" in result.output_text
            assert task.done.is_set() and task.snapshot.status == "failed"
        finally:
            release.set()
            await asyncio.gather(call, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())


def test_parallel_completion_does_not_prune_task_still_fsyncing(
    tmp_path: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager(max_completed_per_session=1)
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = manager._sync_output

        def sync_output(directory: Path, task_id: str) -> None:
            if (directory / f"{task_id}.log").read_text() == "first\n":
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise TimeoutError("test first completion gate was not released")
            original(directory, task_id)

        monkeypatch.setattr(manager, "_sync_output", sync_output)
        try:
            first = await _start(manager, tmp_path, "echo first")
            await asyncio.wait_for(entered.wait(), 2)
            second = await _start(manager, tmp_path, "echo second")
            assert (await manager.wait_task("test", second.task_id, wait_ms=1000)).status == "completed"
            assert not manager._get("test", first.task_id).done.is_set()
            assert not manager._get("test", first.task_id).snapshot.output_expired
            assert (await manager.wait_task("test", first.task_id, wait_ms=1)).status == "running"
            assert (await manager.read_output("test", first.task_id)).output == "first\n"
            release.set()
            completed = await manager.wait_task("test", first.task_id, wait_ms=3000)
            assert completed.status == "completed" and not completed.output_expired
            assert (await manager.read_output("test", first.task_id)).output == "first\n"
            assert [task.task_id for task in await manager.list_tasks("test")] == [first.task_id]
        finally:
            release.set()
            await manager.aclose()

    asyncio.run(run())


def test_parallel_foreground_output_is_pinned_until_bash_consumes_it(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def run() -> None:
        manager = ShellTaskManager(max_completed_per_session=1)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def emit(_: str) -> None:
            entered.set()
            await release.wait()

        first = asyncio.create_task(
            BashTool.call_with_args(
                BashTool.BashArguments(command="printf first"),
                _context(tmp_path, manager).with_emit_tool_output_delta(emit),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task = next(iter(manager._tasks.values()))
            await asyncio.wait_for(task.done.wait(), 2)
            assert not first.done()
            second = await BashTool.call_with_args(
                BashTool.BashArguments(command="printf second"), _context(tmp_path, manager)
            )
            assert second.status == "success" and second.output_text == "second"
            assert manager.read_stream("test", task.snapshot.task_id, "stdout") == b"first"
            release.set()
            result = await asyncio.wait_for(first, 3)
            assert result.status == "success" and result.output_text == "first"
            assert len(manager._tasks) == 1
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)
            await manager.aclose()

    asyncio.run(run())
