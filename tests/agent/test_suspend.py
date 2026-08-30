"""A stream that dies across an OS suspend is reported as a sleep, not a bare transport error."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import klaude_code.agent.step as step_module
from klaude_code.agent.connectivity import is_connectivity_error
from klaude_code.agent.step import StepError, StepExecutionContext, StepExecutor
from klaude_code.agent.suspend import SuspendDetector, suspend_notice
from klaude_code.agent.task import SessionContext
from klaude_code.const import SUSPEND_DETECTION_THRESHOLD_S
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message


class _Clocks:
    """Wall and monotonic clocks driven by hand; ``sleep`` advances only the wall clock."""

    def __init__(self) -> None:
        self.wall = 1_000.0
        self.monotonic = 50.0

    def run(self, seconds: float) -> None:
        self.wall += seconds
        self.monotonic += seconds

    def sleep(self, seconds: float) -> None:
        self.wall += seconds


def _detector(clocks: _Clocks) -> SuspendDetector:
    return SuspendDetector(wall_clock=lambda: clocks.wall, monotonic_clock=lambda: clocks.monotonic)


def test_detector_reports_nothing_while_awake() -> None:
    clocks = _Clocks()
    detector = _detector(clocks)
    clocks.run(600)
    assert detector.suspended_seconds() == 0.0
    assert not detector.suspended()


def test_detector_measures_time_spent_suspended() -> None:
    clocks = _Clocks()
    detector = _detector(clocks)
    clocks.run(5)
    clocks.sleep(3600)
    clocks.run(90)  # keepalive noticed the dead peer after wake
    assert detector.suspended_seconds() == pytest.approx(3600)
    assert detector.suspended()


def test_detector_ignores_gaps_below_the_threshold() -> None:
    clocks = _Clocks()
    detector = _detector(clocks)
    clocks.sleep(SUSPEND_DETECTION_THRESHOLD_S / 2)
    assert not detector.suspended()


def test_suspend_notice_formats_duration() -> None:
    assert suspend_notice(45, partial_output=True) == (
        "Your computer went to sleep mid-response (45s suspended). The response above may be incomplete."
    )
    assert "(12m suspended)" in suspend_notice(12 * 60 + 30, partial_output=True)
    assert "(2h05m suspended)" in suspend_notice(2 * 3600 + 5 * 60, partial_output=True)


def test_suspend_notice_without_output_does_not_point_at_a_response() -> None:
    notice = suspend_notice(3600, partial_output=False)
    assert notice == "Your computer went to sleep mid-request (1h00m suspended) before any response arrived."


class _ErrorStream(LLMStreamABC):
    def __init__(self, error: str, *, partial_text: str | None = "partial answer") -> None:
        self._error = error
        self._partial_text = partial_text

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        if self._partial_text is not None:
            yield message.AssistantTextDelta(content=self._partial_text, response_id="r1")
        yield message.StreamErrorItem(error=self._error)
        yield message.AssistantMessage(
            parts=[message.TextPart(text=self._partial_text or "")],
            response_id="r1",
            stop_reason="error",
        )

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _FakeLLMClient(LLMClientABC):
    def __init__(self, stream: LLMStreamABC) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.ANTHROPIC,
                model_id="claude-sonnet-test",
            )
        )
        self._stream = stream

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        raise NotImplementedError

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        return self._stream


def _build_step_executor(
    error: str, *, partial_text: str | None = "partial answer"
) -> tuple[StepExecutor, list[message.HistoryEvent]]:
    history: list[message.HistoryEvent] = []

    def append_history(items: Sequence[message.HistoryEvent]) -> None:
        history.extend(items)

    session_ctx = SessionContext(
        session_id="session-test",
        work_dir=Path("/tmp"),
        get_conversation_history=lambda: history,
        append_history=append_history,
        file_tracker=cast(Any, SimpleNamespace()),
        file_change_summary=cast(Any, SimpleNamespace()),
        todo_context=cast(Any, SimpleNamespace()),
        run_subtask=None,
        request_user_interaction=None,
    )
    context = StepExecutionContext(
        session_ctx=session_ctx,
        llm_client=_FakeLLMClient(_ErrorStream(error, partial_text=partial_text)),
        system_prompt=None,
        tools=[],
        tool_registry={},
    )
    return StepExecutor(context), history


def _install_suspend(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Make every step see ``seconds`` of suspend between its start and its error."""

    class _SleptDetector:
        def __init__(self) -> None:
            self._seconds = seconds

        def suspended_seconds(self) -> float:
            return self._seconds

        def suspended(self) -> bool:
            return self._seconds >= SUSPEND_DETECTION_THRESHOLD_S

    monkeypatch.setattr(step_module, "SuspendDetector", _SleptDetector)


def _run_to_error(executor: StepExecutor) -> str:
    async def _run() -> str:
        try:
            async for _ in executor.run():
                pass
        except StepError as exc:
            return str(exc)
        raise AssertionError("step did not fail")

    return asyncio.run(_run())


def test_transport_failure_across_a_suspend_is_reported_as_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_suspend(monkeypatch, 3600)
    executor, history = _build_step_executor("APIConnectionError Connection error.")

    error = _run_to_error(executor)

    assert error.startswith("Your computer went to sleep mid-response (1h00m suspended).")
    assert "The response above may be incomplete." in error
    # The raw error stays so the retry policy keeps treating it as unreachable.
    assert error.endswith("APIConnectionError Connection error.")
    assert is_connectivity_error(error)
    # The persisted history item carries the explanation too.
    stream_errors = [item for item in history if isinstance(item, message.StreamErrorItem)]
    assert [item.error for item in stream_errors] == [error]


def test_suspend_before_any_output_is_reported_as_mid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_suspend(monkeypatch, 3600)
    executor, _ = _build_step_executor("APIConnectionError Connection error.", partial_text=None)

    error = _run_to_error(executor)

    assert error.startswith("Your computer went to sleep mid-request (1h00m suspended)")
    assert "response above" not in error
    assert is_connectivity_error(error)


def test_transport_failure_while_awake_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_suspend(monkeypatch, 0)
    executor, _ = _build_step_executor("APIConnectionError Connection error.")

    assert _run_to_error(executor) == "APIConnectionError Connection error."


def test_answered_error_across_a_suspend_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint answered, so the sleep did not cause this failure."""

    _install_suspend(monkeypatch, 3600)
    executor, _ = _build_step_executor("InternalServerError 500 upstream failure")

    assert _run_to_error(executor) == "InternalServerError 500 upstream failure"
