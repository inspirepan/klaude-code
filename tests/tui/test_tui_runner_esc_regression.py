from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, TypeVar, cast

import pytest

from klaude_code.protocol import events, message, op, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session.session import Session
from klaude_code.tui.terminal.selector import QuestionSelectResult

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@dataclass
class _FakeComponents:
    config: Any
    runtime: Any
    display: Any
    event_bus: Any = None

    async def wait_for_display_idle(self) -> None:
        return None


class _FakeDisplay:
    def __init__(
        self,
        *,
        theme: str | None = None,
        on_prompt_suggestion: Any = None,
        on_status_update: Any = None,
    ) -> None:
        self.theme = theme
        self.on_prompt_suggestion = on_prompt_suggestion
        self.on_status_update = on_status_update

    def notify_ask_user_question(self, *, question_count: int, headers: list[str] | None = None) -> None:
        del question_count, headers

    def hide_progress_ui(self) -> None:
        return None

    def show_progress_ui(self) -> None:
        return None

    def set_progress_ui_suspended(self, suspended: bool) -> None:
        del suspended
        return None

    def set_model_name(self, model_name: str) -> None:
        del model_name


class _FakePromptToolkitInput:
    payloads: ClassVar[list[UserInputPayload]] = []
    prefills: ClassVar[list[str | None]] = []
    pending_messages: ClassVar[list[tuple[str, ...]]] = []

    def __init__(self, **_: Any) -> None:
        pass

    async def start(self) -> None:
        return None

    async def iter_inputs(self):
        for payload in list(self.payloads):
            yield payload

    def set_next_prefill(self, text: str | None) -> None:
        self.prefills.append(text)

    def set_session_dir(self, session_dir: Any) -> None:
        pass

    def set_status_lines(self, lines: tuple[str, ...]) -> None:
        del lines
        return None

    def set_pending_messages(self, messages: tuple[str, ...]) -> None:
        self.pending_messages.append(messages)

    def set_dequeue_pending_messages(self, dequeue_pending_messages: Callable[[], tuple[str, ...]] | None) -> None:
        del dequeue_pending_messages

    def set_interrupt_handler(self, request_interrupt: Callable[[], None] | None) -> None:
        del request_interrupt


def _default_question_payload() -> user_interaction.AskUserQuestionRequestPayload:
    return user_interaction.AskUserQuestionRequestPayload(
        questions=[
            user_interaction.AskUserQuestionQuestion(
                id="q1",
                header="Direction",
                question="Choose one",
                options=[
                    user_interaction.AskUserQuestionOption(id="o1", label="A", description="Option A"),
                    user_interaction.AskUserQuestionOption(id="o2", label="B", description="Option B"),
                ],
                multi_select=False,
            )
        ]
    )


def _patch_runner_basics(monkeypatch: pytest.MonkeyPatch):
    import klaude_code.tui.runner as runner

    _FakePromptToolkitInput.prefills = []
    _FakePromptToolkitInput.pending_messages = []

    def _load_config() -> SimpleNamespace:
        return SimpleNamespace(theme="dark")

    def _noop_update_terminal_title(*_args: object, **_kwargs: object) -> None:
        return None

    def _noop_backfill(*_args: object, **_kwargs: object) -> None:
        return None

    async def _noop_cleanup(_components: object) -> None:
        return None

    async def _fake_initialize_session(*_args: object, **_kwargs: object) -> str:
        return "s1"

    def _install_sigint_interrupt(_cb: Callable[[], None]) -> Callable[[], None]:
        return lambda: None

    def _noop_prevent_sleep() -> None:
        return None

    monkeypatch.setattr(runner, "TUIDisplay", _FakeDisplay)
    monkeypatch.setattr(runner, "PromptToolkitInput", _FakePromptToolkitInput)
    monkeypatch.setattr(runner, "load_config", _load_config)
    monkeypatch.setattr(runner, "update_terminal_title", _noop_update_terminal_title)
    monkeypatch.setattr(runner, "backfill_session_model_config", _noop_backfill)
    monkeypatch.setattr(runner, "cleanup_app_components", _noop_cleanup)
    monkeypatch.setattr(runner, "initialize_session", _fake_initialize_session)
    monkeypatch.setattr(runner, "install_sigint_interrupt", _install_sigint_interrupt)
    monkeypatch.setattr(runner, "start_prevent_sleep", _noop_prevent_sleep)
    monkeypatch.setattr(runner, "stop_prevent_sleep", _noop_prevent_sleep)
    monkeypatch.setattr(runner, "force_stop_prevent_sleep", _noop_prevent_sleep)

    return runner


def test_waiting_sigint_triggers_interrupt_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    class _FakeRuntime:
        def __init__(self) -> None:
            self.interrupts: list[op.InterruptOperation] = []
            self._interrupt_received = asyncio.Event()

        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

        async def wait_for(self, _wait_id: str) -> None:
            while sigint_state["on_interrupt"] is None:
                await asyncio.sleep(0)
            sigint_state["on_interrupt"]()
            await asyncio.wait_for(self._interrupt_received.wait(), timeout=1.0)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            if isinstance(operation, op.InterruptOperation):
                self.interrupts.append(operation)
                self._interrupt_received.set()

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(
        runner,
        "submit_user_input_payload",
        _submit_user_input_payload,
    )

    sigint_state: dict[str, Callable[[], None] | None] = {"on_interrupt": None}

    def _install_sigint_interrupt(on_interrupt: Callable[[], None]) -> Callable[[], None]:
        sigint_state["on_interrupt"] = on_interrupt
        return lambda: None

    monkeypatch.setattr(runner, "install_sigint_interrupt", _install_sigint_interrupt)

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert len(runtime.interrupts) == 1
    assert runtime.interrupts[0].session_id == "s1"


def test_busy_input_queues_follow_up_and_drains_after_current_task(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    class _FakeAgent:
        def __init__(self) -> None:
            self.follow_up_inputs: list[UserInputPayload] = []

        def follow_up_count(self) -> int:
            return len(self.follow_up_inputs)

        def follow_up_snapshot(self) -> tuple[UserInputPayload, ...]:
            return tuple(self.follow_up_inputs)

        def pop_next_follow_up(self) -> UserInputPayload | None:
            if not self.follow_up_inputs:
                return None
            return self.follow_up_inputs.pop(0)

    class _FakeRuntime:
        def __init__(self) -> None:
            self.notices: list[events.NoticeEvent] = []
            self._agent = _FakeAgent()

        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> _FakeAgent:
            return self._agent

        async def wait_for(self, _wait_id: str) -> None:
            await asyncio.sleep(0.01)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            if isinstance(operation, op.FollowUpAgentOperation):
                self._agent.follow_up_inputs.append(operation.input)
            return None

        async def emit_event(self, event: events.Event) -> None:
            if isinstance(event, events.NoticeEvent):
                self.notices.append(event)

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    submissions: list[UserInputPayload] = []

    async def _submit_user_input_payload(**kwargs: Any) -> Any:
        submissions.append(kwargs["user_input"])
        return runner.SubmitUserInputResult(wait_id=f"wait-{len(submissions)}")

    monkeypatch.setattr(runner, "submit_user_input_payload", _submit_user_input_payload)

    _FakePromptToolkitInput.payloads = [
        UserInputPayload(text="first"),
        UserInputPayload(text="second while busy"),
        UserInputPayload(text="third while busy"),
        UserInputPayload(text="exit"),
    ]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert [payload.text for payload in submissions] == ["first", "second while busy", "third while busy"]
    assert runtime.current_agent.follow_up_inputs == []
    assert _FakePromptToolkitInput.pending_messages == [
        ("second while busy",),
        ("second while busy", "third while busy"),
        ("third while busy",),
        (),
        (),
    ]
    assert runtime.notices == []


def test_waiting_sigint_restores_prefill_when_no_visible_output(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    class _FakeAgent:
        def __init__(self) -> None:
            self._prefill = "hello"

        def consume_interrupt_prefill_text(self) -> str | None:
            text = self._prefill
            self._prefill = None
            return text

    class _FakeRuntime:
        def __init__(self) -> None:
            self.interrupts: list[op.InterruptOperation] = []
            self._interrupt_received = asyncio.Event()
            self._agent = _FakeAgent()

        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> _FakeAgent:
            return self._agent

        async def wait_for(self, _wait_id: str) -> None:
            while sigint_state["on_interrupt"] is None:
                await asyncio.sleep(0)
            sigint_state["on_interrupt"]()
            await asyncio.wait_for(self._interrupt_received.wait(), timeout=1.0)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            if isinstance(operation, op.InterruptOperation):
                self.interrupts.append(operation)
                self._interrupt_received.set()

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(
        runner,
        "submit_user_input_payload",
        _submit_user_input_payload,
    )

    sigint_state: dict[str, Callable[[], None] | None] = {"on_interrupt": None}

    def _install_sigint_interrupt(on_interrupt: Callable[[], None]) -> Callable[[], None]:
        sigint_state["on_interrupt"] = on_interrupt
        return lambda: None

    monkeypatch.setattr(runner, "install_sigint_interrupt", _install_sigint_interrupt)

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert _FakePromptToolkitInput.prefills == ["hello"]


def test_interaction_collection_runs_without_esc_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    state: dict[str, Any] = {
        "interaction_handler": None,
        "response": None,
    }

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

        async def wait_for(self, _wait_id: str) -> None:
            while state["interaction_handler"] is None:
                await asyncio.sleep(0)

            request_event = events.UserInteractionRequestEvent(
                session_id="s1",
                request_id="req1",
                source="tool",
                tool_call_id="call1",
                payload=_default_question_payload(),
            )
            response = await state["interaction_handler"].collect_response(request_event)
            state["response"] = response

        async def submit_and_wait(self, operation: op.Operation) -> None:
            del operation

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**kwargs: Any) -> _FakeComponents:
        state["interaction_handler"] = kwargs.get("interaction_handler")
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(
        runner,
        "submit_user_input_payload",
        _submit_user_input_payload,
    )

    def _select_questions(**_: Any) -> list[QuestionSelectResult[str]]:
        return [QuestionSelectResult(selected_values=["o1"], input_text="note")]

    monkeypatch.setattr(runner, "select_questions", _select_questions)

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    response = state["response"]
    assert response is not None
    assert response.status == "submitted"


def test_interaction_collection_pauses_prevent_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    calls: list[str] = []
    state: dict[str, Any] = {
        "interaction_handler": None,
        "calls_during_select": [],
    }

    monkeypatch.setattr(runner, "start_prevent_sleep", lambda: calls.append("start"))
    monkeypatch.setattr(runner, "stop_prevent_sleep", lambda: calls.append("stop"))
    monkeypatch.setattr(runner, "force_stop_prevent_sleep", lambda: calls.append("force"))

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

        async def wait_for(self, _wait_id: str) -> None:
            while state["interaction_handler"] is None:
                await asyncio.sleep(0)

            request_event = events.UserInteractionRequestEvent(
                session_id="s1",
                request_id="req1",
                source="tool",
                tool_call_id="call1",
                payload=_default_question_payload(),
            )
            await state["interaction_handler"].collect_response(request_event)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            del operation

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**kwargs: Any) -> _FakeComponents:
        state["interaction_handler"] = kwargs.get("interaction_handler")
        return components

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)
    monkeypatch.setattr(runner, "submit_user_input_payload", _submit_user_input_payload)

    def _select_questions(**_: Any) -> list[QuestionSelectResult[str]]:
        state["calls_during_select"] = list(calls)
        return [QuestionSelectResult(selected_values=["o1"], input_text="")]

    monkeypatch.setattr(runner, "select_questions", _select_questions)

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]
    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert state["calls_during_select"] == ["start", "stop"]
    assert calls == ["start", "stop", "start", "stop", "force"]


def test_operation_model_interaction_uses_model_picker_style(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    state: dict[str, Any] = {
        "interaction_handler": None,
        "response": None,
        "saw_group_header": False,
        "initial_search_text": None,
    }

    class _ModelConfig:
        theme = "dark"
        main_model = "openai@gpt-5"

        def iter_model_entries(self, *, only_available: bool, include_disabled: bool) -> list[Any]:
            del only_available, include_disabled
            return [
                SimpleNamespace(
                    selector="openai@gpt-5",
                    provider="openai",
                    model_id="gpt-5",
                    model_name="GPT-5",
                    thinking=None,
                    effort=None,
                    verbosity=None,
                    fast_mode=False,
                    cache_retention=None,
                    provider_routing=None,
                ),
                SimpleNamespace(
                    selector="anthropic@claude-sonnet-4",
                    provider="anthropic",
                    model_id="claude-sonnet-4",
                    model_name="Claude Sonnet 4",
                    thinking=None,
                    effort=None,
                    verbosity=None,
                    fast_mode=False,
                    cache_retention=None,
                    provider_routing=None,
                ),
            ]

        def resolve_model_location_prefer_available(self, model_name: str) -> None:
            del model_name
            return None

        def resolve_model_location(self, model_name: str) -> tuple[str, str]:
            raise ValueError(model_name)

    monkeypatch.setattr(runner, "load_config", lambda: _ModelConfig())

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

        async def wait_for(self, _wait_id: str) -> None:
            while state["interaction_handler"] is None:
                await asyncio.sleep(0)

            request_event = events.UserInteractionRequestEvent(
                session_id="s1",
                request_id="req-model",
                source="operation_model",
                payload=user_interaction.OperationSelectRequestPayload(
                    header="Model",
                    question="Select a model:",
                    initial_search_text="sonnet",
                    options=[
                        user_interaction.OperationSelectOption(
                            id="openai@gpt-5",
                            label="openai@gpt-5",
                            description="openai / gpt-5",
                        ),
                        user_interaction.OperationSelectOption(
                            id="anthropic@claude-sonnet-4",
                            label="anthropic@claude-sonnet-4",
                            description="anthropic / claude-sonnet-4",
                        ),
                    ],
                ),
            )
            state["response"] = await state["interaction_handler"].collect_response(request_event)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            del operation

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**kwargs: Any) -> _FakeComponents:
        state["interaction_handler"] = kwargs.get("interaction_handler")
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(runner, "submit_user_input_payload", _submit_user_input_payload)

    def _select_one(**kwargs: Any) -> str:
        items = kwargs["items"]
        state["saw_group_header"] = any(not item.selectable for item in items)
        state["initial_search_text"] = kwargs.get("initial_search_text")
        return "anthropic@claude-sonnet-4"

    monkeypatch.setattr(runner, "select_one", _select_one)

    def _fail_select_questions(**_: Any) -> None:
        raise AssertionError("operation_model should not use ask_user_question UI")

    monkeypatch.setattr(
        runner,
        "select_questions",
        _fail_select_questions,
    )

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]
    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    response = state["response"]
    assert response is not None
    assert response.status == "submitted"
    assert response.payload is not None
    assert response.payload.kind == "operation_select"
    assert response.payload.selected_option_id == "anthropic@claude-sonnet-4"
    assert state["saw_group_header"] is True
    assert state["initial_search_text"] == "sonnet"


def test_operation_thinking_interaction_uses_selector_style(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    state: dict[str, Any] = {
        "interaction_handler": None,
        "response": None,
        "select_one_called": 0,
    }

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

        async def wait_for(self, _wait_id: str) -> None:
            while state["interaction_handler"] is None:
                await asyncio.sleep(0)

            request_event = events.UserInteractionRequestEvent(
                session_id="s1",
                request_id="req-thinking",
                source="operation_thinking",
                payload=user_interaction.OperationSelectRequestPayload(
                    header="Thinking",
                    question="Choose one",
                    options=[
                        user_interaction.OperationSelectOption(id="o1", label="A", description="Option A"),
                        user_interaction.OperationSelectOption(id="o2", label="B", description="Option B"),
                    ],
                ),
            )
            state["response"] = await state["interaction_handler"].collect_response(request_event)

        async def submit_and_wait(self, operation: op.Operation) -> None:
            del operation

    runtime = _FakeRuntime()
    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=runtime,
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**kwargs: Any) -> _FakeComponents:
        state["interaction_handler"] = kwargs.get("interaction_handler")
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id="wait-1")

    monkeypatch.setattr(runner, "submit_user_input_payload", _submit_user_input_payload)

    def _select_one(**_: Any) -> str:
        state["select_one_called"] += 1
        return "o2"

    monkeypatch.setattr(runner, "select_one", _select_one)

    def _fail_select_questions(**_: Any) -> None:
        raise AssertionError("operation_thinking should not use ask_user_question UI")

    monkeypatch.setattr(
        runner,
        "select_questions",
        _fail_select_questions,
    )

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="hello"), UserInputPayload(text="exit")]
    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    response = state["response"]
    assert response is not None
    assert response.status == "submitted"
    assert response.payload is not None
    assert response.payload.kind == "operation_select"
    assert response.payload.selected_option_id == "o2"
    assert state["select_one_called"] == 1


def test_exit_cleans_empty_session(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home
    runner = _patch_runner_basics(monkeypatch)

    session = Session.create(id="s1", work_dir=Path.cwd())
    session.ensure_meta_exists()
    assert Session.exists("s1", work_dir=Path.cwd())

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=_FakeRuntime(),
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)
    _FakePromptToolkitInput.payloads = [UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert not Session.exists("s1", work_dir=Path.cwd())


def test_exit_keeps_non_empty_session(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home
    runner = _patch_runner_basics(monkeypatch)

    session = Session.create(id="s1", work_dir=Path.cwd())

    async def _seed_session() -> None:
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        await session.wait_for_flush()

    arun(_seed_session())
    assert Session.exists("s1", work_dir=Path.cwd())

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=_FakeRuntime(),
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)
    _FakePromptToolkitInput.payloads = [UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert Session.exists("s1", work_dir=Path.cwd())


def test_exit_without_user_messages_skips_resume_hint(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home
    runner = _patch_runner_basics(monkeypatch)

    session = Session.create(id="s1", work_dir=Path.cwd())

    async def _seed_session() -> None:
        session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("hello"))])
        await session.wait_for_flush()

    arun(_seed_session())
    assert Session.exists("s1", work_dir=Path.cwd())

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=_FakeRuntime(),
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    log_messages: list[str] = []

    def _log(*parts: object) -> None:
        log_messages.append(" ".join(str(part) for part in parts))

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)
    monkeypatch.setattr(runner, "log", _log)
    _FakePromptToolkitInput.payloads = [UserInputPayload(text="exit")]

    arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert Session.exists("s1", work_dir=Path.cwd())
    assert not any(message.startswith("Session ID:") for message in log_messages)
    assert not any(message.startswith("Resume with:") for message in log_messages)


def test_keyboard_interrupt_without_user_messages_skips_resume_hint(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    from klaude_code.app import runtime as app_runtime
    from klaude_code.app.runtime_facade import RuntimeFacade

    session = Session.create(id="s1", work_dir=Path.cwd())
    session.ensure_meta_exists()

    log_messages: list[str] = []

    def _log(*parts: object) -> None:
        log_messages.append(" ".join(str(part) for part in parts))

    monkeypatch.setattr(app_runtime, "log", _log)

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        def has_running_tasks(self) -> bool:
            return False

    arun(app_runtime.handle_keyboard_interrupt(cast(RuntimeFacade, _FakeRuntime())))

    assert any(message == "Bye!" for message in log_messages)
    assert not any(message.startswith("Resume with:") for message in log_messages)


def test_web_mode_transition_skips_exit_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _patch_runner_basics(monkeypatch)

    requested = runner.WebModeRequest(host="0.0.0.0", port=9000, no_open=True, debug=None)

    class _FakeRuntime:
        def current_session_id(self) -> str | None:
            return "s1"

        @property
        def current_agent(self) -> None:
            return None

    components = _FakeComponents(
        config=SimpleNamespace(main_model=None),
        runtime=_FakeRuntime(),
        display=_FakeDisplay(theme="dark"),
    )

    async def _init_components(**_: Any) -> _FakeComponents:
        return components

    monkeypatch.setattr(runner, "initialize_app_components", _init_components)

    async def _submit_user_input_payload(**_: Any) -> Any:
        return runner.SubmitUserInputResult(wait_id=None, web_mode_request=requested)

    monkeypatch.setattr(runner, "submit_user_input_payload", _submit_user_input_payload)

    cleanup_calls: list[object] = []

    async def _cleanup(components: object) -> None:
        cleanup_calls.append(components)

    monkeypatch.setattr(runner, "cleanup_app_components", _cleanup)

    log_messages: list[str] = []

    def _log(*parts: object) -> None:
        log_messages.append(" ".join(str(part) for part in parts))

    def _session_exists(*_args: object, **_kwargs: object) -> bool:
        return True

    def _load_session(*_args: object, **_kwargs: object) -> Any:
        return SimpleNamespace(messages_count=1)

    def _shortest_unique_prefix(*_args: object, **_kwargs: object) -> str:
        return "s1"

    monkeypatch.setattr(runner, "log", _log)
    monkeypatch.setattr(Session, "exists", _session_exists)
    monkeypatch.setattr(Session, "load", _load_session)
    monkeypatch.setattr(Session, "shortest_unique_prefix", _shortest_unique_prefix)

    _FakePromptToolkitInput.payloads = [UserInputPayload(text="/web")]

    result = arun(runner.run_interactive(runner.AppInitConfig(model=None, debug=False, vanilla=False), session_id="s1"))

    assert result == requested
    assert cleanup_calls == [components]
    assert not any(message.startswith("Session ID:") for message in log_messages)
    assert not any(message.startswith("Resume with:") for message in log_messages)
