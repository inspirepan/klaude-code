from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from klaude_code.const import BASH_TERMINATE_TIMEOUT_SEC, ProjectPaths, project_key_from_path
from klaude_code.protocol.shell_task import ShellTaskOutput, ShellTaskSnapshot
from klaude_code.tool.core.ansi import strip_ansi

type UpdateCallback = Callable[[str, list[ShellTaskSnapshot]], Awaitable[None]]
type CompleteCallback = Callable[[ShellTaskSnapshot], Awaitable[None]]
_ACTIVE = {"running", "stopping"}


@dataclass
class _Task:
    snapshot: ShellTaskSnapshot
    directory: Path
    process: asyncio.subprocess.Process | None = None
    monitor: asyncio.Task[None] | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    notified: bool = False
    output_size: int = 0
    merged_size: int = 0
    quota_hit: bool = False
    on_success: Callable[[], None] | None = None
    foreground_consumed: bool = False


class ShellTaskManager:
    """Own live process groups; persisted PIDs are diagnostic, never kill targets."""

    def __init__(
        self,
        on_update: UpdateCallback | None = None,
        on_complete: CompleteCallback | None = None,
        *,
        max_output_bytes: int = 16 * 1024 * 1024,
        max_running_per_session: int = 16,
        max_completed_per_session: int = 64,
        storage_root: Path | None = None,
    ) -> None:
        self._on_update = on_update
        self._on_complete = on_complete
        self._max_output_bytes = max_output_bytes
        self._max_running = max_running_per_session
        self._max_completed = max_completed_per_session
        self._tasks: dict[str, _Task] = {}
        self._loaded: set[tuple[str, str]] = set()
        self._start_lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._prune_lock = asyncio.Lock()
        self._closed = False
        self._storage_root = storage_root
        if min(max_output_bytes, max_running_per_session, max_completed_per_session) <= 0:
            raise ValueError("Shell task resource limits must be positive")

    def set_callbacks(self, *, on_update: UpdateCallback | None, on_complete: CompleteCallback | None) -> None:
        self._on_update = on_update
        self._on_complete = on_complete

    def _directory(self, session_id: str, work_dir: Path) -> Path:
        if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
            raise ValueError("Invalid session ID")
        if self._storage_root is not None:
            return self._storage_root / session_id / "shell_tasks"
        return ProjectPaths(project_key_from_path(work_dir)).session_dir(session_id) / "shell_tasks"

    @staticmethod
    def _write_snapshot(directory: Path, task_id: str, payload: str) -> None:
        path = directory / f"{task_id}.json"
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8") as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        temporary.replace(path)
        if os.name == "posix":
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    async def _persist(self, task: _Task) -> None:
        async with task.write_lock:
            payload = task.snapshot.model_dump_json()
            write = asyncio.create_task(
                asyncio.to_thread(self._write_snapshot, task.directory, task.snapshot.task_id, payload)
            )
            cancelled = False
            # Keep ownership of the write until its thread finishes, even on cancellation.
            # A subsequent state write must never overtake this one.
            while not write.done():
                try:
                    await asyncio.shield(write)
                except asyncio.CancelledError:
                    cancelled = True
            write.result()
            if cancelled:
                raise asyncio.CancelledError

    async def _load(self, session_id: str, work_dir: Path) -> None:
        async with self._load_lock:
            await self._load_session(session_id, work_dir)

    async def _load_session(self, session_id: str, work_dir: Path) -> None:
        key = (session_id, str(work_dir.resolve()))
        if key in self._loaded:
            return
        directory = self._directory(session_id, work_dir)
        directory.mkdir(parents=True, exist_ok=True)
        loaded: list[_Task] = []
        for path in directory.glob("*.json"):
            try:
                if path.is_symlink():
                    continue
                fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(fd, "r", encoding="utf-8") as reader:
                    snapshot = ShellTaskSnapshot.model_validate_json(reader.read())
                if snapshot.session_id != session_id or snapshot.task_id != path.stem:
                    continue
                if uuid.UUID(snapshot.task_id).hex != snapshot.task_id:
                    continue
                if snapshot.task_id in self._tasks:
                    continue
                # Never trust paths or PIDs read from disk.
                snapshot.output_path = str(directory / f"{snapshot.task_id}.log")
                task = _Task(snapshot, directory, notified=True, foreground_consumed=True)
                if snapshot.status in _ACTIVE:
                    snapshot.status = "lost"
                    snapshot.ended_at = time.time()
                    snapshot.reason = "Server restarted; process ownership was lost."
                    await self._persist(task)
                task.done.set()
                loaded.append(task)
            except (OSError, ValueError):
                continue
        for task in sorted(loaded, key=lambda item: item.snapshot.ended_at or item.snapshot.started_at)[
            -self._max_completed :
        ]:
            self._tasks[task.snapshot.task_id] = task
        self._loaded.add(key)

    def _get(self, session_id: str, task_id: str) -> _Task:
        task = self._tasks.get(task_id)
        if task is None or task.snapshot.session_id != session_id:
            raise ValueError("Shell task not found in this session")
        return task

    @staticmethod
    def _snapshot(task: _Task) -> ShellTaskSnapshot:
        snapshot = task.snapshot.model_copy(deep=True)
        if not task.done.is_set() and snapshot.status not in _ACTIVE:
            snapshot.status = "stopping" if snapshot.status == "stopped" else "running"
            snapshot.exit_code = None
            snapshot.ended_at = None
        return snapshot

    async def list_tasks(self, session_id: str, *, work_dir: Path | None = None) -> list[ShellTaskSnapshot]:
        if work_dir is not None:
            await self._load(session_id, work_dir)
        return [
            self._snapshot(task)
            for task in sorted(self._tasks.values(), key=lambda item: item.snapshot.started_at)
            if task.snapshot.session_id == session_id and task.snapshot.background
        ]

    async def _publish(self, task: _Task) -> None:
        if self._closed:
            return
        if self._on_update is not None:
            with contextlib.suppress(Exception):
                await self._on_update(task.snapshot.session_id, await self.list_tasks(task.snapshot.session_id))
        if self._closed:
            return
        if task.snapshot.background and task.done.is_set() and not task.notified:
            task.notified = True
            if self._on_complete is not None:
                with contextlib.suppress(Exception):
                    await self._on_complete(task.snapshot.model_copy(deep=True))

    async def start(
        self,
        *,
        session_id: str,
        work_dir: Path,
        command: str,
        description: str,
        timeout_ms: int | None,
        env: dict[str, str],
        background: bool = False,
        on_success: Callable[[], None] | None = None,
    ) -> ShellTaskSnapshot:
        async with self._start_lock:
            if self._closed:
                raise ValueError("Shell task manager is closed")
            await self._load(session_id, work_dir)
            if (
                sum(t.snapshot.session_id == session_id and not t.done.is_set() for t in self._tasks.values())
                >= self._max_running
            ):
                raise ValueError("Session running shell task limit reached")
            task_id = uuid.uuid4().hex
            directory = self._directory(session_id, work_dir)
            snapshot = ShellTaskSnapshot(
                task_id=task_id,
                session_id=session_id,
                work_dir=str(work_dir.resolve()),
                command=command,
                description=description,
                status="running",
                background=background,
                started_at=time.time(),
                output_path=str(directory / f"{task_id}.log"),
            )
            task = _Task(snapshot, directory, on_success=on_success)
            for suffix in ("log", "stdout", "stderr"):
                (directory / f"{task_id}.{suffix}").touch()
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    "bash",
                    "-lc",
                    f"set -o pipefail\n{command}",
                    cwd=work_dir,
                    env=env,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=os.name == "posix",
                )
            )
            cancelled = False
            # A cancelled spawn can already have created a child. Register its handle
            # before propagating cancellation so it cannot escape manager ownership.
            while not spawn.done():
                try:
                    await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    cancelled = True
            process = spawn.result()
            task.process = process
            snapshot.pid = process.pid
            self._tasks[task_id] = task
            try:
                async with task.lock:
                    task.monitor = asyncio.create_task(self._monitor(task, timeout_ms))
                    await self._persist(task)
                    if cancelled:
                        raise asyncio.CancelledError
            except (OSError, asyncio.CancelledError):
                task.foreground_consumed = True
                snapshot.status = "stopping"
                await asyncio.shield(task.done.wait())
                raise
        if background:
            await asyncio.shield(self._publish(task))
        return self._snapshot(task)

    async def background_task(self, session_id: str, task_id: str) -> ShellTaskSnapshot:
        task = self._get(session_id, task_id)
        cancelled = False
        async with task.lock:
            task.snapshot.background = True
            try:
                await self._persist(task)
            except asyncio.CancelledError:
                cancelled = True
        await asyncio.shield(self._publish(task))
        if cancelled:
            raise asyncio.CancelledError
        return self._snapshot(task)

    async def _drain(self, task: _Task, reader: asyncio.StreamReader, suffix: str) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")

        def bounded_text(text: str) -> bytes:
            data = text.encode("utf-8")
            remaining = self._max_output_bytes - task.merged_size
            if len(data) > remaining:
                task.quota_hit = True
                data = data[:remaining].decode("utf-8", errors="ignore").encode("utf-8")
            task.merged_size += len(data)
            return data

        with (
            (task.directory / f"{task.snapshot.task_id}.{suffix}").open("ab") as stream,
            Path(task.snapshot.output_path).open("ab") as merged,
        ):
            while data := await reader.read(8192):
                remaining = self._max_output_bytes - task.output_size
                if len(data) > remaining:
                    task.quota_hit = True
                    data = data[: max(0, remaining)]
                task.output_size += len(data)
                stream.write(data)
                stream.flush()
                text = decoder.decode(data)
                merged.write(bounded_text(text))
                merged.flush()
            merged.write(bounded_text(decoder.decode(b"", final=True)))
            merged.flush()

    async def _kill_group(self, task: _Task) -> None:
        proc = task.process
        if proc is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, sig)
                elif proc.returncode is None:
                    proc.terminate() if sig == signal.SIGTERM else proc.kill()
            except ProcessLookupError:
                return
            if sig == signal.SIGTERM:
                await asyncio.sleep(BASH_TERMINATE_TIMEOUT_SEC)

    @staticmethod
    def _close_output_pipes(proc: asyncio.subprocess.Process) -> None:
        # asyncio exposes no public method for closing only the parent's read ends.
        # Escaped descendants may retain writers, so EOF is not a reliable boundary.
        transport = getattr(proc, "_transport", None)
        if transport is not None:
            for descriptor in (1, 2):
                pipe = transport.get_pipe_transport(descriptor)
                if pipe is not None:
                    pipe.close()

    @staticmethod
    def _sync_output(directory: Path, task_id: str) -> None:
        for suffix in ("log", "stdout", "stderr"):
            fd = os.open(directory / f"{task_id}.{suffix}", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as reader:
                os.fsync(reader.fileno())

    async def _monitor(self, task: _Task, timeout_ms: int | None) -> None:
        proc = task.process
        assert proc is not None and proc.stdout is not None and proc.stderr is not None
        drains = [
            asyncio.create_task(self._drain(task, proc.stdout, "stdout")),
            asyncio.create_task(self._drain(task, proc.stderr, "stderr")),
        ]
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        terminal_status: str | None = None
        cleanup: asyncio.Task[None] | None = None
        cleanup_deadline: float | None = None
        try:
            while True:
                now = time.monotonic()
                streams_done = all(drain.done() for drain in drains)
                if any(drain.done() and drain.exception() is not None for drain in drains):
                    terminal_status = "failed"
                    task.snapshot.reason = "Could not write shell output to persistent storage."
                if task.quota_hit:
                    terminal_status = "failed"
                    task.snapshot.reason = f"Output quota exceeded ({self._max_output_bytes} bytes)."
                if deadline is not None and now >= deadline and (proc.returncode is None or not streams_done):
                    terminal_status = "timed_out"
                    task.snapshot.reason = f"Timeout after {timeout_ms} ms running: {task.snapshot.command}"
                if cleanup is None and (
                    proc.returncode is not None or terminal_status is not None or task.snapshot.status == "stopping"
                ):
                    cleanup = asyncio.create_task(self._kill_group(task))
                    cleanup_deadline = now + BASH_TERMINATE_TIMEOUT_SEC + 0.2
                if cleanup is not None:
                    if (
                        cleanup.done()
                        and proc.returncode is not None
                        and (streams_done or terminal_status is not None or task.snapshot.status == "stopping")
                    ):
                        cleanup.result()
                        break
                    if cleanup_deadline is not None and now >= cleanup_deadline:
                        if terminal_status is None and task.snapshot.status != "stopping":
                            terminal_status = "failed"
                            task.snapshot.reason = "Output streams did not close after shell cleanup; escaped descendants may still be running."
                        break
                await asyncio.sleep(0.02)
            self._close_output_pipes(proc)
            for drain in drains:
                if not drain.done():
                    drain.cancel()
            await asyncio.gather(*drains, return_exceptions=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(proc.wait(), 0.2)
            async with task.lock:
                rc = proc.returncode
                if rc == 128 + int(getattr(signal, "SIGPIPE", 13)):
                    rc = 0
                task.snapshot.exit_code = rc
                if task.quota_hit:
                    task.snapshot.status = "failed"
                    task.snapshot.reason = f"Output quota exceeded ({self._max_output_bytes} bytes)."
                elif task.snapshot.status == "stopping":
                    task.snapshot.status = "stopped"
                elif terminal_status == "timed_out":
                    task.snapshot.status = "timed_out"
                elif terminal_status == "failed":
                    task.snapshot.status = "failed"
                elif task.snapshot.status == "running":
                    task.snapshot.status = "completed" if rc == 0 else "failed"
                task.snapshot.ended_at = time.time()
                on_success, task.on_success = task.on_success, None
                if task.snapshot.status == "completed" and on_success is not None:
                    with contextlib.suppress(Exception):
                        on_success()
                on_success = None
                await asyncio.to_thread(self._sync_output, task.directory, task.snapshot.task_id)
                await self._persist(task)
            # Reserve the incoming completion, but only prune records already done.
            await self._prune(task.snapshot.session_id, reserve=1)
            task.done.set()
        except Exception as error:
            if cleanup is None:
                await self._kill_group(task)
            async with task.lock:
                task.snapshot.status = "failed"
                task.snapshot.reason = f"Shell task management failed: {error}"
                task.snapshot.ended_at = time.time()
                with contextlib.suppress(OSError):
                    await self._persist(task)
        finally:
            self._close_output_pipes(proc)
            for drain in drains:
                if not drain.done():
                    drain.cancel()
            await asyncio.gather(*drains, return_exceptions=True)
            if cleanup is not None:
                if not cleanup.done():
                    cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)
            task.on_success = None
            task.done.set()
            if task.snapshot.background:
                await self._publish(task)

    async def _prune(self, session_id: str, *, reserve: int = 0) -> None:
        async with self._prune_lock:
            await self._prune_session(session_id, reserve=reserve)

    async def _prune_session(self, session_id: str, *, reserve: int) -> None:
        completed = sorted(
            (t for t in self._tasks.values() if t.snapshot.session_id == session_id and t.done.is_set()),
            key=lambda t: t.snapshot.ended_at or t.snapshot.started_at,
        )
        excess = max(0, len(completed) + reserve - self._max_completed)
        eligible = [t for t in completed if t.snapshot.background or t.foreground_consumed]
        for task in eligible[:excess]:
            async with task.lock:
                task.snapshot.output_expired = True
                await self._persist(task)
                for suffix in ("log", "stdout", "stderr"):
                    with contextlib.suppress(FileNotFoundError):
                        await asyncio.to_thread((task.directory / f"{task.snapshot.task_id}.{suffix}").unlink)
                self._tasks.pop(task.snapshot.task_id, None)

    async def release_foreground(self, session_id: str, task_id: str) -> None:
        task = self._get(session_id, task_id)
        task.foreground_consumed = True
        await self._prune(session_id)

    async def read_output(
        self, session_id: str, task_id: str, *, offset: int = 0, limit: int = 16384
    ) -> ShellTaskOutput:
        if offset < 0 or limit <= 0:
            raise ValueError("offset must be nonnegative and limit must be positive")
        task = self._get(session_id, task_id)
        fd = os.open(task.snapshot.output_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as reader:
            reader.seek(offset)
            data = reader.read(min(limit, 1024 * 1024))
            # Complete a split UTF-8 codepoint rather than replacing it between pages.
            for _ in range(3):
                try:
                    text = data.decode("utf-8")
                    break
                except UnicodeDecodeError as error:
                    if error.reason != "unexpected end of data":
                        text = data.decode("utf-8", errors="replace")
                        break
                    extra = reader.read(1)
                    if not extra:
                        data = data[: error.start]
                        text = data.decode("utf-8", errors="replace")
                        break
                    data += extra
            else:
                text = data.decode("utf-8", errors="replace")
            next_offset = offset + len(data)
            truncated = next_offset < os.fstat(reader.fileno()).st_size
        return ShellTaskOutput(
            task=self._snapshot(task),
            output=strip_ansi(text),
            next_offset=next_offset,
            truncated=truncated,
        )

    def read_stream(self, session_id: str, task_id: str, suffix: str, offset: int = 0) -> bytes:
        if suffix not in {"stdout", "stderr"}:
            raise ValueError("Invalid output stream")
        task = self._get(session_id, task_id)
        fd = os.open(task.directory / f"{task_id}.{suffix}", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as reader:
            reader.seek(offset)
            return reader.read(self._max_output_bytes)

    async def wait_task(self, session_id: str, task_id: str, *, wait_ms: int = 10000) -> ShellTaskSnapshot:
        if wait_ms < 0:
            raise ValueError("wait_ms must be nonnegative")
        task = self._get(session_id, task_id)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(task.done.wait(), wait_ms / 1000)
        return self._snapshot(task)

    async def stop_task(self, session_id: str, task_id: str) -> ShellTaskSnapshot:
        task = self._get(session_id, task_id)
        async with task.lock:
            if task.snapshot.status in _ACTIVE:
                task.snapshot.status = "stopping"
                task.snapshot.reason = "Stopped by user."
                await self._persist(task)
        if task.snapshot.background:
            await self._publish(task)
        await task.done.wait()
        return self._snapshot(task)

    async def stop_session(self, session_id: str) -> None:
        await asyncio.gather(
            *(
                self.stop_task(session_id, t.snapshot.task_id)
                for t in list(self._tasks.values())
                if t.snapshot.session_id == session_id and not t.done.is_set()
            )
        )

    def active_session_ids(self) -> set[str]:
        return {t.snapshot.session_id for t in self._tasks.values() if not t.done.is_set()}

    def has_running_tasks(self) -> bool:
        return bool(self.active_session_ids())

    async def aclose(self) -> None:
        self._closed = True
        self.set_callbacks(on_update=None, on_complete=None)
        async with self._start_lock:
            session_ids = self.active_session_ids()
        await asyncio.gather(*(self.stop_session(sid) for sid in session_ids))
        await asyncio.gather(
            *(t.monitor for t in self._tasks.values() if t.monitor is not None), return_exceptions=True
        )
