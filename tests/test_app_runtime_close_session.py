from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeVar, cast

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import events, model, user_interaction

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _pending_request(request_id: str, session_id: str) -> PendingUserInteractionRequest:
    return PendingUserInteractionRequest(
        request_id=request_id,
        session_id=session_id,
        source="tool",
        tool_call_id=None,
        payload=user_interaction.AskUserQuestionRequestPayload(
            questions=[
                user_interaction.AskUserQuestionQuestion(
                    id="q1",
                    header="h",
                    question="q",
                    options=[
                        user_interaction.AskUserQuestionOption(id="o1", label="A", description="d"),
                        user_interaction.AskUserQuestionOption(id="o2", label="B", description="d"),
                    ],
                )
            ]
        ),
    )


def test_close_session_force_emits_interaction_cancelled_and_resolved_events() -> None:
    class _StubSessionRegistry:
        def __init__(self) -> None:
            self.cancelled = [_pending_request("req1", "s1")]

        def cancel_pending_interactions_with_requests(
            self,
            *,
            session_id: str | None = None,
        ) -> list[PendingUserInteractionRequest]:
            assert session_id == "s1"
            return list(self.cancelled)

        async def close_session(self, session_id: str, *, force: bool = False) -> bool:
            assert session_id == "s1"
            assert force is True
            return True

    class _StubOperationDispatcher:
        def __init__(self) -> None:
            self.events: list[tuple[events.Event, dict[str, str | None]]] = []

        async def emit_event(
            self,
            event: events.Event,
            *,
            operation_id: str | None = None,
            task_id: str | None = None,
            causation_id: str | None = None,
        ) -> None:
            self.events.append(
                (
                    event,
                    {
                        "operation_id": operation_id,
                        "task_id": task_id,
                        "causation_id": causation_id,
                    },
                )
            )

    async def _test() -> None:
        runtime_any = cast(Any, object.__new__(RuntimeFacade))
        runtime_any.session_registry = _StubSessionRegistry()
        runtime_any._operation_dispatcher = _StubOperationDispatcher()

        runtime = cast(RuntimeFacade, runtime_any)
        closed = await RuntimeFacade.close_session(runtime, "s1", force=True)
        assert closed is True

        executor = runtime_any._operation_dispatcher
        recorded = executor.events
        assert len(recorded) == 2

        first_event, first_meta = recorded[0]
        second_event, second_meta = recorded[1]

        assert isinstance(first_event, events.UserInteractionCancelledEvent)
        assert first_event.request_id == "req1"
        assert first_event.reason == "session_close"
        assert first_meta["causation_id"] == "req1"

        assert isinstance(second_event, events.UserInteractionResolvedEvent)
        assert second_event.request_id == "req1"
        assert second_event.status == "cancelled"
        assert second_meta["causation_id"] == "req1"

    arun(_test())


def test_runtime_stop_persists_running_sessions_as_idle(monkeypatch: Any, tmp_path: Path) -> None:
    persisted: list[tuple[str, model.SessionRuntimeState, Path]] = []

    class _StubSession:
        def __init__(self, work_dir: Path) -> None:
            self.work_dir = work_dir
            self.session_state = model.SessionRuntimeState.RUNNING
            self.flushed = False

        async def wait_for_flush(self) -> None:
            self.flushed = True

    class _StubRuntime:
        def __init__(self, session_id: str, session: _StubSession) -> None:
            self.session_id = session_id
            self._agent = SimpleNamespace(session=session)

        def get_agent(self) -> Any:
            return self._agent

    class _StubSessionRegistry:
        def __init__(self, runtime: _StubRuntime) -> None:
            self.runtime = runtime
            self.stopped = False

        def list_session_actors(self) -> list[_StubRuntime]:
            return [self.runtime]

        async def stop(self) -> None:
            self.stopped = True

    class _StubOperationDispatcher:
        def __init__(self, task: asyncio.Task[None]) -> None:
            self.task = task
            self.cleared = False

        def cancel_pending_user_interactions(self, *, session_id: str | None = None) -> list[Any]:
            assert session_id is None
            return []

        async def emit_event(
            self,
            event: events.Event,
            *,
            operation_id: str | None = None,
            task_id: str | None = None,
            causation_id: str | None = None,
        ) -> None:
            raise AssertionError(f"unexpected event: {event}")

        def list_active_tasks(self) -> list[Any]:
            return [SimpleNamespace(task=self.task)]

        def clear_active_tasks(self) -> None:
            self.cleared = True

    class _StubOperationAwaiter:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    def _persist_runtime_state(session_id: str, session_state: model.SessionRuntimeState, work_dir: Path) -> None:
        persisted.append((session_id, session_state, work_dir))

    monkeypatch.setattr(
        "klaude_code.session.session.Session.persist_runtime_state",
        _persist_runtime_state,
    )

    async def _test() -> None:
        runtime_any = cast(Any, object.__new__(RuntimeFacade))
        session = _StubSession(tmp_path)
        actor = _StubRuntime("s1", session)
        runtime_any.session_registry = _StubSessionRegistry(actor)

        task = asyncio.create_task(asyncio.sleep(10))
        runtime_any._operation_dispatcher = _StubOperationDispatcher(task)
        runtime_any._operation_awaiter = _StubOperationAwaiter()
        runtime_any._stopped = False

        runtime = cast(RuntimeFacade, runtime_any)
        await RuntimeFacade.stop(runtime)

        assert task.cancelled() is True
        assert session.flushed is True
        assert session.session_state == model.SessionRuntimeState.IDLE
        assert persisted == [("s1", model.SessionRuntimeState.IDLE, tmp_path)]
        assert runtime_any.session_registry.stopped is True
        assert runtime_any._operation_awaiter.stopped is True
        assert runtime_any._operation_dispatcher.cleared is True

    arun(_test())
