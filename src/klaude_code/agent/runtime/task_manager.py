"""Durable task references and delivery receipts, not a second session scheduler."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

from klaude_code.agent.runtime.agent_activity import update_agent_activity
from klaude_code.const import ProjectPaths, project_key_from_path
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.protocol.background_task import (
    ACTIVE_TASK_STATUSES,
    TASK_DELIVERY_ID_PREFIX,
    TASK_RESULT_SUMMARY_MAX_CHARS,
    AgentActivity,
    BackgroundTaskResult,
    BackgroundTaskSnapshot,
    TaskReference,
    TaskRequest,
    TaskResponse,
)
from klaude_code.protocol.models import TaskMetadataItem, merge_file_changes
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session
from klaude_code.tool.core.disk import write_snapshot
from klaude_code.tool.shell.task_manager import ShellTaskManager


class TaskManager:
    @staticmethod
    def has_durable_agent_results(owner: str, work_dir: Path) -> bool:
        """Detect interrupted/unread agents without loading or reviving tasks."""
        directory = ProjectPaths(project_key_from_path(work_dir)).session_dir(owner) / "background_tasks"
        for path in directory.glob("*.json"):
            try:
                if path.is_symlink():
                    continue
                task = BackgroundTaskSnapshot.model_validate_json(path.read_text())
                if (
                    task.ref.owner_session_id == owner
                    and task.ref.task_id == path.stem
                    and UUID(task.ref.task_id).hex == task.ref.task_id
                    and task.ref.kind == "agent"
                    and not task.delivered
                    and not task.expected_stop
                    and not task.output_unavailable
                ):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def __init__(
        self,
        shell: ShellTaskManager | None,
        stop_agent: Callable[[TaskReference], Awaitable[None]],
        emit: Callable[[events.Event], Awaitable[None]],
        *,
        pin_owner: Callable[[str, str, bool], None] | None = None,
    ) -> None:
        self.shell = shell
        self._stop_agent = stop_agent
        self._emit = emit
        self._pin_owner = pin_owner
        self._records: dict[str, BackgroundTaskSnapshot] = {}
        self._directories: dict[str, Path] = {}
        self._collectors: dict[str, asyncio.Task[None]] = {}
        self._launches: dict[str, BackgroundTaskSnapshot] = {}
        self._registered: dict[str, asyncio.Event] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._loaded: set[tuple[str, str]] = set()
        self._work_dirs: dict[str, Path] = {}
        self._closed = False
        self._write_locks: dict[str, asyncio.Lock] = {}
        self._persisted: dict[str, str] = {}
        self._load_lock = asyncio.Lock()
        self._settle_locks: dict[str, asyncio.Lock] = {}
        self._settled: set[tuple[str, str]] = set()
        self._restored_results: set[str] = set()
        self._activity: dict[str, AgentActivity] = {}

    def record_agent_event(self, task_id: str, event: events.Event) -> None:
        """Update live facts only; streaming events never cause disk writes or publications."""
        task = self._records.get(task_id)
        if task is None or task.status not in ACTIVE_TASK_STATUSES:
            return
        activity = update_agent_activity(self._activity.get(task_id), event)
        if activity is not None:
            self._activity[task_id] = activity

    async def _persist(self, task: BackgroundTaskSnapshot) -> None:
        task_id = task.ref.task_id
        async with self._write_locks.setdefault(task_id, asyncio.Lock()):
            payload = task.model_dump_json()
            if self._persisted.get(task_id) == payload:
                return
            write = asyncio.create_task(asyncio.to_thread(write_snapshot, self._directories[task_id], task_id, payload))
            cancelled = False
            while not write.done():
                try:
                    await asyncio.shield(write)
                except asyncio.CancelledError:
                    cancelled = True
            write.result()
            self._persisted[task_id] = payload
            if cancelled:
                raise asyncio.CancelledError

    async def _load(self, owner: str, work_dir: Path) -> None:
        async with self._load_lock:
            await self._load_session(owner, work_dir)

    async def _load_session(self, owner: str, work_dir: Path) -> None:
        key = (owner, str(work_dir.resolve()))
        if key in self._loaded:
            return
        if not owner or Path(owner).name != owner or owner in {".", ".."}:
            raise ValueError("Invalid owner session ID")
        directory = ProjectPaths(project_key_from_path(work_dir)).session_dir(owner) / "background_tasks"
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.glob("*.json"):
            try:
                if path.is_symlink():
                    continue
                task = BackgroundTaskSnapshot.model_validate_json(path.read_text())
                if task.ref.owner_session_id != owner or task.ref.task_id != path.stem:
                    continue
                if UUID(task.ref.task_id).hex != task.ref.task_id or task.ref.task_id in self._records:
                    continue
                self._directories[task.ref.task_id] = directory
                self._records[task.ref.task_id] = task
                self._persisted[task.ref.task_id] = task.model_dump_json()
                if (
                    task.ref.kind == "agent"
                    and not task.delivered
                    and not task.expected_stop
                    and not task.output_unavailable
                ):
                    self._restored_results.add(task.ref.task_id)
                if task.ref.kind == "agent" and task.status in ACTIVE_TASK_STATUSES:
                    task.status = "lost"
                    task.ended_at = time.time()
                    task.result = BackgroundTaskResult(
                        text="Server restarted; original agent run was interrupted.", error=True
                    )
                    await self._persist(task)
                done = self._done.setdefault(task.ref.task_id, asyncio.Event())
                if task.status not in ACTIVE_TASK_STATUSES:
                    done.set()
            except (OSError, ValueError):
                continue
        self._loaded.add(key)
        self._work_dirs[owner] = work_dir

    async def _register(self, task: BackgroundTaskSnapshot, work_dir: Path) -> None:
        await self._load(task.ref.owner_session_id, work_dir)
        directory = (
            ProjectPaths(project_key_from_path(work_dir)).session_dir(task.ref.owner_session_id) / "background_tasks"
        )
        self._directories[task.ref.task_id] = directory
        self._records[task.ref.task_id] = task
        self._done[task.ref.task_id] = asyncio.Event()
        await self._persist(task)

    async def _publish(self, owner: str, work_dir: Path) -> None:
        await self._emit(
            events.BackgroundTasksUpdatedEvent(session_id=owner, tasks=await self.list_tasks(owner, work_dir))
        )

    async def start_agent(
        self,
        owner: str,
        work_dir: Path,
        description: str,
        run: Callable[[str, Callable[[str, str], Awaitable[None]]], Awaitable[SubAgentResult]],
        *,
        agent_type: str | None = None,
        on_result: Callable[[], Awaitable[None]] | None = None,
    ) -> BackgroundTaskSnapshot:
        if self._closed:
            raise ValueError("Task manager is closed")
        task_id = uuid4().hex
        task = BackgroundTaskSnapshot(
            ref=TaskReference(kind="agent", owner_session_id=owner, task_id=task_id, run_id=task_id),
            status="queued",
            description=description,
            agent_type=agent_type,
            started_at=time.time(),
            delivery_id=f"{TASK_DELIVERY_ID_PREFIX}{task_id}",
        )
        # Pin before the first await: an idle owner cannot be released mid-launch.
        if self._pin_owner is not None:
            self._pin_owner(owner, task_id, True)
        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        ready.add_done_callback(lambda future: future.exception() if not future.cancelled() else None)
        self._launches[task_id] = task
        self._registered[task_id] = asyncio.Event()

        async def started(session_id: str, operation_id: str) -> None:
            task.ref.session_id = session_id
            task.ref.operation_id = operation_id
            task.status = "stopping" if task.expected_stop else "running"
            await self._persist(task)
            if not ready.done():
                ready.set_result(None)

        async def collect() -> None:
            launch_error: Exception | None = None
            try:
                try:
                    await self._register(task, work_dir)
                finally:
                    self._registered[task_id].set()
                result = await run(task_id, started)
                task.result = BackgroundTaskResult(
                    text=result.task_result,
                    error=result.error,
                    metadata=result.task_metadata,
                    file_changes=result.file_changes,
                )
                if result.status == "lost":
                    task.status = "lost"
                elif not result.error:
                    task.status = "completed"
                elif task.expected_stop or result.status == "stopped":
                    task.status = "stopped"
                    task.expected_stop = True
                else:
                    task.status = "failed"
                if task.status == "completed":
                    task.expected_stop = False
            except asyncio.CancelledError:
                task.result = BackgroundTaskResult(
                    text="Agent collector interrupted; execution cannot be confirmed.", error=True
                )
                task.status = "lost"
                if not ready.done():
                    ready.cancel()
                raise
            except Exception as exc:
                task.result = BackgroundTaskResult(text=f"Agent launch/run failed: {exc}", error=True)
                task.status = "stopped" if task.expected_stop else "failed"
                launch_error = exc
            finally:
                task.ended_at = time.time()
                activity = self._activity.get(task_id)
                if activity is not None:
                    activity.active_tools.clear()
                    if activity.phase != "finished":
                        activity.phase = "finished"
                        activity.phase_started_at = task.ended_at
                try:
                    if task_id in self._directories:
                        await self._persist(task)
                    if on_result is not None:
                        try:
                            await on_result()
                        except Exception as exc:
                            log_debug(f"Deferred task accounting for {task_id}: {exc}", debug_type=DebugType.EXECUTION)
                    with contextlib.suppress(Exception):
                        await self._publish(owner, work_dir)
                finally:
                    self._done.setdefault(task_id, asyncio.Event()).set()
                    if self._pin_owner is not None:
                        self._pin_owner(owner, task_id, False)
                    if not ready.done():
                        if launch_error is not None:
                            ready.set_exception(launch_error)
                        else:
                            ready.set_result(None)

        self._collectors[task_id] = asyncio.create_task(collect(), name=f"agent-collector:{task_id}")

        def collected(future: asyncio.Task[None]) -> None:
            self._collectors.pop(task_id, None)
            self._launches.pop(task_id, None)
            self._registered.pop(task_id, None)
            if future.cancelled():
                return
            error = future.exception()
            if error is not None:
                log_debug(f"Task collector failed for {task_id}: {error}", debug_type=DebugType.EXECUTION)

        self._collectors[task_id].add_done_callback(collected)
        # Parent cancellation never transfers ownership of the collector.
        await asyncio.shield(ready)
        await self._publish(owner, work_dir)
        return task.model_copy(deep=True)

    async def list_tasks(self, owner: str, work_dir: Path) -> list[BackgroundTaskSnapshot]:
        await self._load(owner, work_dir)
        if self.shell is not None:
            for shell in await self.shell.list_tasks(owner, work_dir=work_dir):
                await self.record_shell(shell, work_dir)
        return [self._snapshot(task) for task in self._records.values() if task.ref.owner_session_id == owner]

    def _snapshot(self, task: BackgroundTaskSnapshot) -> BackgroundTaskSnapshot:
        snapshot = task.model_copy(deep=True)
        if task.ref.task_id in self._activity:
            snapshot.activity = self._activity[task.ref.task_id].model_copy(deep=True)
        # Text is paginated by output/wait, not duplicated in every list/event.
        if snapshot.result is not None:
            snapshot.result.summary = snapshot.result.text[:TASK_RESULT_SUMMARY_MAX_CHARS] or None
            snapshot.result.text = ""
        return snapshot

    async def record_shell(self, shell: ShellTaskSnapshot, work_dir: Path) -> None:
        await self._load(shell.session_id, work_dir)
        task = self._records.get(shell.task_id)
        if task is None:
            task = BackgroundTaskSnapshot(
                ref=TaskReference(
                    kind="shell", owner_session_id=shell.session_id, task_id=shell.task_id, run_id=shell.task_id
                ),
                status=shell.status,
                description=shell.description,
                started_at=shell.started_at,
                delivery_id=f"{TASK_DELIVERY_ID_PREFIX}{shell.task_id}",
                shell=shell.model_copy(deep=True),
                ended_at=shell.ended_at,
                expected_stop=shell.status in {"stopping", "stopped"},
                output_unavailable=shell.output_expired,
            )
            await self._register(task, work_dir)
        else:
            task.status = shell.status
            task.shell = shell.model_copy(deep=True)
            task.ended_at = shell.ended_at
            task.expected_stop = shell.status in {"stopping", "stopped"}
            task.output_unavailable = task.output_unavailable or shell.output_expired
            task.shell.output_expired = task.output_unavailable
            await self._persist(task)
        if task.status not in ACTIVE_TASK_STATUSES:
            self._done[task.ref.task_id].set()

    def _get(self, owner: str, task_id: str) -> BackgroundTaskSnapshot:
        task = self._records.get(task_id)
        if task is None or task.ref.owner_session_id != owner:
            raise ValueError("Task not found in this owner session")
        return task

    async def manage(
        self, session_id: str, work_dir: Path, request: TaskRequest, *, activity: asyncio.Event | None = None
    ) -> TaskResponse:
        tasks = await self.list_tasks(session_id, work_dir)
        if request.action == "list":
            return TaskResponse(tasks=tasks)
        if request.task_id is None:
            raise ValueError("task_id is required except for list")
        task = self._get(session_id, request.task_id)
        if request.action == "stop":
            await self.stop_task(session_id, task.ref.task_id)
        interrupted = False
        if request.action == "wait" and not self._done[task.ref.task_id].is_set():
            if task.ref.kind == "shell":
                assert self.shell is not None
                waiter = asyncio.create_task(
                    self.shell.wait_task(session_id, task.ref.task_id, wait_ms=request.wait_ms)
                )
            else:
                waiter = asyncio.create_task(self._done[task.ref.task_id].wait())
            steering = asyncio.create_task(activity.wait()) if activity is not None else None
            try:
                waits = {waiter} if steering is None else {waiter, steering}
                finished, _ = await asyncio.wait(
                    waits, timeout=request.wait_ms / 1000, return_when=asyncio.FIRST_COMPLETED
                )
                interrupted = (
                    steering is not None and steering in finished and not self._done[task.ref.task_id].is_set()
                )
            finally:
                for future in (waiter, steering):
                    if future is not None:
                        future.cancel()
                await asyncio.gather(
                    *(future for future in (waiter, steering) if future is not None), return_exceptions=True
                )
        await self.list_tasks(session_id, work_dir)
        interrupted = interrupted and task.status in ACTIVE_TASK_STATUSES
        response = TaskResponse(
            tasks=[self._snapshot(task)], interrupted_wait=interrupted, output_unavailable=task.output_unavailable
        )
        if request.action in {"output", "wait"}:
            output_available = True
            if task.output_unavailable:
                response.output = "Output expired or unavailable."
                output_available = False
            elif task.ref.kind == "shell":
                assert self.shell is not None
                try:
                    page = await self.shell.read_output(
                        session_id, task.ref.task_id, offset=request.offset, limit=request.limit
                    )
                    response.output, response.next_offset, response.truncated = (
                        page.output,
                        page.next_offset,
                        page.truncated,
                    )
                except (FileNotFoundError, ValueError) as exc:
                    if isinstance(exc, ValueError) and str(exc) != "Shell task not found in this session":
                        raise
                    response.output = "Output expired or unavailable."
                    output_available = False
                    task.output_unavailable = True
                    if task.shell is not None:
                        task.shell.output_expired = True
                    await self._persist(task)
                    response.output_unavailable = True
                    response.tasks = [self._snapshot(task)]
            elif task.result is not None:
                data = task.result.text.encode("utf-8")
                end = min(len(data), request.offset + request.limit)
                while end < len(data) and data[end] & 0xC0 == 0x80:
                    end += 1
                response.output = data[request.offset : end].decode("utf-8", errors="replace")
                response.next_offset, response.truncated = end, end < len(data)
            if (
                task.status not in ACTIVE_TASK_STATUSES
                and request.offset == 0
                and not response.truncated
                and output_available
            ):
                response.delivery_id = task.delivery_id
        return response

    async def stop_task(self, owner: str, task_id: str) -> None:
        launch = self._launches.get(task_id)
        if launch is not None and launch.ref.owner_session_id == owner:
            await self._registered[task_id].wait()
            if task_id not in self._records:
                await self._done.setdefault(task_id, asyncio.Event()).wait()
                return
        task = self._get(owner, task_id)
        if task.status not in ACTIVE_TASK_STATUSES:
            return
        task.expected_stop = True
        task.status = "stopping"
        await self._persist(task)
        if task.ref.kind == "shell":
            assert self.shell is not None
            await self.record_shell(await self.shell.stop_task(owner, task_id), self._work_dirs[owner])
        else:
            # A queued launch must first register its operation identity.
            while task.ref.operation_id is None and not self._done[task_id].is_set():
                await asyncio.sleep(0.001)
            if not self._done[task_id].is_set():
                await self._stop_agent(task.ref.model_copy(deep=True))
                await self._done[task_id].wait()

    async def stop_sub_agents(self, owner: str, work_dir: Path) -> None:
        collectors = {
            task_id: self._collectors[task_id]
            for task_id, task in self._launches.items()
            if task.ref.owner_session_id == owner
        }
        await asyncio.gather(*(self._registered[task_id].wait() for task_id in collectors))
        tasks = await self.list_tasks(owner, work_dir)
        results = await asyncio.gather(
            *(
                self.stop_task(owner, task.ref.task_id)
                for task in tasks
                if task.ref.kind == "agent" and task.status in ACTIVE_TASK_STATUSES
            ),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise RuntimeError("Stopping child tasks failed: " + "; ".join(str(exc) for exc in failures))
        await asyncio.gather(*collectors.values(), return_exceptions=True)

    async def pending_results(self, owner: str, work_dir: Path) -> list[BackgroundTaskSnapshot]:
        return [
            task
            for task in await self.list_tasks(owner, work_dir)
            if task.status not in ACTIVE_TASK_STATUSES
            and not task.delivered
            and not task.expected_stop
            and not task.output_unavailable
        ]

    async def stop_all_tasks(self, owner: str, work_dir: Path) -> None:
        actions = [self.stop_sub_agents(owner, work_dir)]
        if self.shell is not None:
            actions.append(self.shell.stop_session(owner))
        results = await asyncio.gather(*actions, return_exceptions=True)
        await self.list_tasks(owner, work_dir)
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            raise RuntimeError("Stopping owned tasks failed: " + "; ".join(str(exc) for exc in failures))

    async def settle_agent_results(self, session: Session) -> None:
        """Apply durable per-run accounting once, independently of any parent turn."""
        async with self._settle_locks.setdefault(session.id, asyncio.Lock()):
            await self._settle_agent_results(session)

    async def _settle_agent_results(self, session: Session) -> None:
        await self._load(session.id, session.work_dir)
        batch: list[TaskMetadataItem] = []
        for task in self._records.values():
            if task.ref.owner_session_id != session.id or task.ref.kind != "agent" or task.result is None:
                continue
            if (session.id, task.ref.task_id) in self._settled:
                continue
            if task.ref.task_id not in session.background_task_ids:
                merge_file_changes(session.file_change_summary, task.result.file_changes or [])
                session.background_task_ids.add(task.ref.task_id)
            batch.append(
                TaskMetadataItem(
                    background_task_id=task.ref.task_id,
                    sub_agent_task_metadata=[task.result.metadata] if task.result.metadata is not None else [],
                )
            )
        if batch:
            session.append_history(batch, deduplicate_background_tasks=True)
            await session.wait_for_background_task_flush()
        self._settled.update(
            (session.id, item.background_task_id) for item in batch if item.background_task_id is not None
        )

    async def acknowledge(self, owner: str, delivery_id: str) -> None:
        for task in list(self._records.values()):
            if (
                task.ref.owner_session_id == owner
                and task.delivery_id == delivery_id
                and task.status not in ACTIVE_TASK_STATUSES
            ):
                task.delivered = True
                await self._persist(task)

    def active_owner_ids(self) -> set[str]:
        return {task.ref.owner_session_id for task in self._launches.values()} | {
            task.ref.owner_session_id
            for task in self._records.values()
            if task.status in ACTIVE_TASK_STATUSES or task.ref.task_id in self._collectors
        }

    def session_tasks_snapshot(self, owner: str) -> list[BackgroundTaskSnapshot]:
        """Read already loaded task facts without loading or changing execution."""
        records = {**self._records, **self._launches}
        return [self._snapshot(task) for task in records.values() if task.ref.owner_session_id == owner]

    def has_restored_results(self, owner: str) -> bool:
        """Recovered reports need an operator-established continuation path."""
        return any(
            task_id in self._restored_results
            and task.ref.owner_session_id == owner
            and not task.delivered
            and not task.expected_stop
            and not task.output_unavailable
            for task_id, task in self._records.items()
        )

    async def aclose(self) -> None:
        self._closed = True
        collectors = list(self._collectors.values())
        await asyncio.gather(*(registered.wait() for registered in self._registered.values()))
        await asyncio.gather(
            *(
                self.stop_task(task.ref.owner_session_id, task.ref.task_id)
                for task in list(self._records.values())
                if task.ref.kind == "agent" and task.status in ACTIVE_TASK_STATUSES
            )
        )
        await asyncio.gather(*collectors, return_exceptions=True)
