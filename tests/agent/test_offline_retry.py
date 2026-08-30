"""Step retry policy when the LLM endpoint cannot be reached.

A suspended machine makes every step fail at connect. Those failures must not
spend the bounded step-retry budget, or a task left running overnight is dead
long before the user returns.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import klaude_code.agent.task as task_module
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.connectivity import is_connectivity_error
from klaude_code.agent.step import StepError
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.const import MAX_FAILED_STEP_RETRIES, OFFLINE_RETRY_WINDOW_S
from klaude_code.protocol import events, message
from klaude_code.session.session import Session
from klaude_code.session.store_registry import close_default_store
from klaude_code.tool.core.context import build_todo_context


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


def _never_compact(**_: Any) -> bool:
    return False


@pytest.fixture(autouse=True)
def _no_compaction(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)


class _FakeClock:
    """Stand-in for ``task.time`` whose monotonic clock advances on every read.

    The whole module attribute is replaced rather than ``time.monotonic``
    itself: that function is the asyncio event loop's own clock, so patching it
    globally would break scheduling inside the test.
    """

    def __init__(self, step: float) -> None:
        self._now = 0.0
        self._step = step

    def monotonic(self) -> float:
        self._now += self._step
        return self._now

    def perf_counter(self) -> float:
        return self._now


def _build_executor(session: Session) -> TaskExecutor:
    llm_config = SimpleNamespace(model_id="test-model", effective_effort=None)
    llm_client = SimpleNamespace(model_name="test-model", get_llm_config=lambda: llm_config)
    session_ctx = SessionContext(
        session_id=session.id,
        work_dir=session.work_dir,
        get_conversation_history=session.get_llm_history,
        append_history=session.append_history,
        file_tracker=session.file_tracker,
        file_change_summary=session.file_change_summary,
        todo_context=build_todo_context(session),
        run_subtask=None,
        request_user_interaction=None,
    )
    profile = AgentProfile(llm_client=cast(Any, llm_client), system_prompt=None, tools=[], attachments=[])
    return TaskExecutor(
        TaskExecutionContext(
            session=session,
            session_ctx=session_ctx,
            profile=profile,
            tool_registry={},
            sub_agent_state=None,
        )
    )


def _install_failing_step(
    monkeypatch: pytest.MonkeyPatch,
    error_for: Callable[[int], str],
    *,
    preserved_partial_output: bool = False,
) -> list[int]:
    """Fail every step with ``error_for(attempt)``; returns the attempt log."""

    attempts: list[int] = []

    class StubStepExecutor:
        def __init__(self, _: Any) -> None:
            self.task_finished = False
            self.continue_agent = True
            self.task_result = None
            self.preserved_partial_output = preserved_partial_output

        async def run(self) -> AsyncGenerator[events.Event]:
            attempts.append(1)
            if False:
                yield cast(events.Event, None)
            raise StepError(error_for(len(attempts)))

    monkeypatch.setattr(task_module, "StepExecutor", StubStepExecutor)
    return attempts


async def _run_task(project_dir: Path) -> list[events.Event]:
    session = Session.create(work_dir=project_dir)
    session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
    executor = _build_executor(session)
    collected = [event async for event in executor.run(message.UserInputPayload(text="hello"))]
    await close_default_store()
    return collected


def _final_error(collected: list[events.Event]) -> str:
    fatal = [e for e in collected if isinstance(e, events.ErrorEvent) and not e.can_retry]
    assert len(fatal) == 1
    return fatal[0].error_message


def _record_backoff_attempts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace the backoff with a no-wait stub recording the attempt numbers."""

    recorded: list[int] = []

    def _fake_delay(attempt: int) -> float:
        recorded.append(attempt)
        return 0.0

    monkeypatch.setattr(task_module, "_retry_delay_seconds", _fake_delay)
    return recorded


def test_unreachable_endpoint_retries_past_the_step_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    # A 20th of the window per clock reading, so an endpoint that never comes
    # back exhausts the window in ~20 attempts instead of the real ~60, while
    # still overrunning the 10-retry budget a reachable endpoint would get.
    monkeypatch.setattr(task_module, "time", _FakeClock(OFFLINE_RETRY_WINDOW_S / 20))
    backoff_attempts = _record_backoff_attempts(monkeypatch)
    attempts = _install_failing_step(monkeypatch, lambda _: "APIConnectionError Connection error.")

    collected = arun(_run_task(project_dir))

    # Retried past the budget a reachable endpoint would get, then the window
    # (not the attempt counter) ended the task.
    assert len(attempts) > MAX_FAILED_STEP_RETRIES + 1
    assert "unreachable" in _final_error(collected)
    retry_notices = [e for e in collected if isinstance(e, events.ErrorEvent) and e.can_retry]
    assert len(retry_notices) == len(attempts) - 1
    assert "Endpoint unreachable for 0s" in retry_notices[0].error_message
    # Same backoff ladder as a reachable endpoint: a blip still retries fast.
    assert backoff_attempts == list(range(1, len(attempts)))


def test_answered_error_still_aborts_on_the_step_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    _record_backoff_attempts(monkeypatch)
    attempts = _install_failing_step(monkeypatch, lambda _: "InternalServerError 500 upstream failure")

    collected = arun(_run_task(project_dir))

    assert len(attempts) == MAX_FAILED_STEP_RETRIES + 1
    assert f"Step failed after {MAX_FAILED_STEP_RETRIES} retries." in _final_error(collected)


def test_partial_output_keeps_a_dropped_stream_on_the_step_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each such retry re-sends the preserved partial answer, so it must be capped."""

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    _record_backoff_attempts(monkeypatch)
    attempts = _install_failing_step(
        monkeypatch,
        lambda _: "RemoteProtocolError peer closed connection",
        preserved_partial_output=True,
    )

    collected = arun(_run_task(project_dir))

    assert len(attempts) == MAX_FAILED_STEP_RETRIES + 1
    assert f"Step failed after {MAX_FAILED_STEP_RETRIES} retries." in _final_error(collected)


def test_recovered_endpoint_gets_the_full_step_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable stretch must not eat the budget of the errors after it."""

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    backoff_attempts = _record_backoff_attempts(monkeypatch)
    unreachable_attempts = 3
    attempts = _install_failing_step(
        monkeypatch,
        lambda attempt: "ConnectError " if attempt <= unreachable_attempts else "InternalServerError 500 upstream",
    )

    collected = arun(_run_task(project_dir))

    assert len(attempts) == unreachable_attempts + MAX_FAILED_STEP_RETRIES + 1
    assert f"Step failed after {MAX_FAILED_STEP_RETRIES} retries." in _final_error(collected)
    # The unreachable stretch runs its own ladder; the answered errors restart it.
    assert backoff_attempts == list(range(1, unreachable_attempts + 1)) + list(range(1, MAX_FAILED_STEP_RETRIES + 1))


@pytest.mark.parametrize(
    "error",
    [
        "APIConnectionError Connection error.",
        "APITimeoutError Request timed out.",
        "ConnectError [Errno 8] nodename nor servname provided, or not known",
        "ConnectTimeout ",
        "ReadError ",
        "RemoteProtocolError Server disconnected without sending a response.",
        "EndpointConnectionError Could not connect to the endpoint URL",
    ],
)
def test_transport_failures_are_connectivity_errors(error: str) -> None:
    assert is_connectivity_error(error)


@pytest.mark.parametrize(
    "error",
    [
        "",
        "InternalServerError 500 upstream failure",
        "RateLimitError 429 too many requests",
        "BadRequestError prompt is too long: 210000 tokens > 200000 maximum",
        "AuthenticationError insufficient_quota",
    ],
)
def test_answered_failures_are_not_connectivity_errors(error: str) -> None:
    assert not is_connectivity_error(error)
