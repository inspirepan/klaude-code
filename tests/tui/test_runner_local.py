"""Runner behavior tests against an in-memory RuntimeClient fake.

The local runner is exercised with fakes for RuntimeClient, prompt-toolkit,
and display: turn submission, busy queues, Esc prefill, exit cleanup and
/new switching. Native scheduling is covered in tests/app/test_local_agent_e2e.py.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, Literal

import pytest

import klaude_code.tui.runner as runner_module
from klaude_code.protocol import events, op, user_interaction
from klaude_code.protocol.background_task import TaskRequest, TaskResponse
from klaude_code.protocol.message import UserInputPayload
from klaude_code.protocol.model_catalog import ModelCatalog, ModelCatalogEntry
from klaude_code.tui.client.base import SessionInfoSnapshot
from klaude_code.tui.terminal.selector import SelectItem, _build_choices_tokens

# -- fakes ------------------------------------------------------------------

_DEFAULT_SELECTOR = runner_module.select_one


def test_removed_detach_command_does_not_exit_local_runtime() -> None:
    assert not runner_module._is_exit_input("/detach")


class FakeRuntimeClient:
    def __init__(self, session_id: str = "sess-1") -> None:
        self._session_id = session_id
        self.submitted: list[op.Operation] = []
        self.emitted_user_messages: list[events.UserMessageEvent] = []
        self.local_events: list[events.Event] = []
        self.switched_to: list[str] = []
        self.closed = False
        self.dequeue_calls = 0
        self.task_requests: list[TaskRequest] = []
        self.model_catalog = ModelCatalog(models=[], revision=0)
        self.hold_run_ops = False
        self.owned_tasks_running = False

        self._info = SessionInfoSnapshot(session_id=session_id, work_dir="/nonexistent-work-dir")
        self._running = False
        self._active_operation_id: str | None = None
        self._steering: list[str] = []
        self._state_changed = asyncio.Event()
        self.interaction_closed = Event()
        self._interaction_queue: asyncio.Queue[events.UserInteractionRequestEvent] = asyncio.Queue()
        self._interrupt_prefill: str | None = None
        self._blocked_ops: dict[str, asyncio.Event] = {}

    # test controls
    def set_running(self, running: bool) -> None:
        self._running = running
        if not running:
            self._active_operation_id = None
        self._state_changed.set()

    def set_active_operation(self, operation_id: str) -> None:
        self._running = True
        self._active_operation_id = operation_id
        self._state_changed.set()

    def set_prefill(self, text: str | None) -> None:
        # Mirrors production: arming the retract prefill wakes the watcher.
        self._interrupt_prefill = text
        self._state_changed.set()

    def release_operations(self) -> None:
        for gate in self._blocked_ops.values():
            gate.set()

    def ops_of[OpT: op.Operation](self, op_type: type[OpT]) -> list[OpT]:
        return [item for item in self.submitted if isinstance(item, op_type)]

    # RuntimeClient protocol
    @property
    def session_id(self) -> str:
        return self._session_id

    async def start(self) -> None:
        return None

    def has_running_tasks(self) -> bool:
        return self._running or self.owned_tasks_running

    def command_agent(self):
        return SimpleNamespace(
            session=runner_module.Session.load_meta(self.session_id, work_dir=Path("/nonexistent-work-dir")),
            profile=None,
        )

    async def create_session(self) -> str:
        return "new-session"

    async def close(self) -> None:
        self.closed = True
        self._running = False

    async def switch_session(self, session_id: str) -> None:
        self.switched_to.append(session_id)
        self._session_id = session_id
        self._state_changed.set()

    def start_display(self) -> None:
        return None

    async def wait_for_display_idle(self) -> None:
        return None

    async def wait_for_replay_complete(self) -> None:
        return None

    async def submit(self, operation: op.Operation) -> str:
        self.submitted.append(operation)
        if self.hold_run_ops and isinstance(operation, op.RunAgentOperation):
            # Simulate an operation whose finish trails (task wind-down).
            self._blocked_ops.setdefault(operation.id, asyncio.Event())
        if isinstance(operation, op.SteerAgentOperation):
            self._steering.append(operation.input.text)
            self._info.steering = tuple(self._steering)
            self._state_changed.set()
        return operation.id

    async def wait_for(self, operation_id: str) -> None:
        gate = self._blocked_ops.get(operation_id)
        if gate is not None:
            await gate.wait()

    async def submit_and_wait(self, operation: op.Operation) -> None:
        await self.submit(operation)
        await self.wait_for(operation.id)

    async def emit_user_message(self, event: events.UserMessageEvent) -> None:
        self.emitted_user_messages.append(event)

    async def emit_local_event(self, event: events.Event) -> None:
        self.local_events.append(event)

    async def dequeue_pending_messages(self) -> tuple[str, ...]:
        self.dequeue_calls += 1
        texts = (*self._steering, *self._info.follow_ups)
        self._steering.clear()
        self._info.steering = ()
        self._info.follow_ups = ()
        self._state_changed.set()
        return texts

    async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
        self.task_requests.append(request)
        return TaskResponse(tasks=[])

    async def get_model_catalog(self) -> ModelCatalog:
        return self.model_catalog

    def is_running(self) -> bool:
        return self._running

    def active_operation_id(self) -> str | None:
        return self._active_operation_id

    def steering_texts(self) -> tuple[str, ...]:
        return self._info.steering

    def follow_up_texts(self) -> tuple[str, ...]:
        return self._info.follow_ups

    def optimistically_append_follow_ups(self, texts: Sequence[str]) -> None:
        self._info.follow_ups = (*self._info.follow_ups, *texts)
        self._state_changed.set()

    def remove_optimistic_follow_up(self, text: str) -> None:
        texts = list(self._info.follow_ups)
        for index in range(len(texts) - 1, -1, -1):
            if texts[index] == text:
                del texts[index]
                break
        self._info.follow_ups = tuple(texts)
        self._state_changed.set()

    def optimistically_append_steering(self, texts: Sequence[str]) -> None:
        self._info.steering = (*self._info.steering, *texts)
        self._state_changed.set()

    def remove_optimistic_steering(self, text: str) -> None:
        steering = list(self._info.steering)
        for idx in range(len(steering) - 1, -1, -1):
            if steering[idx] == text:
                del steering[idx]
                break
        self._info.steering = tuple(steering)
        self._state_changed.set()

    def session_info(self) -> SessionInfoSnapshot:
        return self._info

    def consume_interrupt_prefill(self) -> str | None:
        text = self._interrupt_prefill
        self._interrupt_prefill = None
        return text

    def state_changed_event(self) -> asyncio.Event:
        return self._state_changed

    def interaction_closed_event(self, request: events.UserInteractionRequestEvent) -> Event:
        return self.interaction_closed

    def interaction_requests(self) -> asyncio.Queue[events.UserInteractionRequestEvent]:
        return self._interaction_queue


type Script = Callable[[FakeRuntimeClient, "FakeInputProvider"], AsyncGenerator[UserInputPayload]]


class FakeInputProvider:
    """Scripted stand-in for PromptToolkitInput."""

    instance: FakeInputProvider | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.agent_running_states: list[bool] = []
        self.pending_messages: list[tuple[str, ...]] = []
        self.prefills: list[str | None] = []
        self.interrupt_handler: Callable[[], None] | None = None
        self.startup_loading: list[bool] = []
        self.exit_requests = 0
        self.input_text = ""
        self.call_log: list[tuple[str, Any]] = []
        self._script: AsyncGenerator[UserInputPayload] | None = None
        FakeInputProvider.instance = self

    def bind_script(self, script: AsyncGenerator[UserInputPayload]) -> None:
        self._script = script

    async def start(self) -> None:
        on_prompt_start = self.kwargs.get("on_prompt_start")
        if callable(on_prompt_start):
            on_prompt_start()

    def iter_inputs(self) -> AsyncGenerator[UserInputPayload]:
        assert self._script is not None
        return self._script

    # state sinks
    def set_agent_running(self, running: bool) -> None:
        self.agent_running_states.append(running)
        self.call_log.append(("agent_running", running))

    def set_interrupt_handler(self, handler: Callable[[], None] | None) -> None:
        self.interrupt_handler = handler

    def has_input_text(self) -> bool:
        return bool(self.input_text)

    def set_pending_messages(self, messages: tuple[str, ...]) -> None:
        self.pending_messages.append(messages)

    def set_pending_follow_ups(self, messages: tuple[str, ...]) -> None:
        self.pending_follow_ups = messages

    def set_next_prefill(self, text: str | None) -> None:
        self.prefills.append(text)
        self.call_log.append(("prefill", text))

    def set_startup_loading(self, loading: bool) -> None:
        self.startup_loading.append(loading)

    def set_startup_loading_title(self, title: str | None) -> None:
        del title

    def request_exit(self) -> None:
        self.exit_requests += 1

    def set_prompt_suggestion(self, text: str | None) -> None:
        del text

    def set_status_lines(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def set_stream_lines(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs

    def set_dequeue_pending_messages(self, fn: Callable[[], Awaitable[tuple[str, ...]]]) -> None:
        self.dequeue_fn = fn

    async def pause_for_external_input(self) -> Callable[[], None]:
        return lambda: None

    async def choose_task_action(self, *args: Any, **kwargs: Any) -> str | None:
        return None

    def close_task_overlay(self) -> None:
        return None


class FakeDisplay:
    def locate_session(self) -> None:
        pass

    def task_attention(self) -> dict[str, str]:
        return {}

    def __init__(self, **kwargs: Any) -> None:
        self.envelopes: list[events.EventEnvelope] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        self.envelopes.append(envelope)

    def set_model_name(self, name: str | None) -> None:
        del name

    def hide_progress_ui(self, *, flush_open_blocks: bool = True) -> None:
        del flush_open_blocks

    def show_progress_ui(self) -> None:
        return None

    def set_progress_ui_suspended(self, suspended: bool) -> None:
        del suspended

    def refresh_prompt_status(self) -> None:
        return None

    def notify_ask_user_question(self, **kwargs: Any) -> None:
        del kwargs


# -- harness ----------------------------------------------------------------


def run_scenario(
    monkeypatch: pytest.MonkeyPatch,
    script_factory: Callable[[FakeRuntimeClient], AsyncGenerator[UserInputPayload]],
    *,
    client: FakeRuntimeClient | None = None,
    setup: Callable[[FakeRuntimeClient], Awaitable[None]] | None = None,
) -> FakeRuntimeClient:
    fake_client = client or FakeRuntimeClient()
    if runner_module.select_one is _DEFAULT_SELECTOR:
        monkeypatch.setattr(runner_module, "select_one", lambda **_kwargs: True)

    monkeypatch.setattr(runner_module, "LocalRuntimeClient", lambda *a, **k: fake_client)
    monkeypatch.setattr(runner_module, "PromptToolkitInput", FakeInputProvider)
    monkeypatch.setattr(runner_module, "TUIDisplay", FakeDisplay)
    monkeypatch.setattr(runner_module, "update_terminal_title", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "configure_pt_theme", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "is_light_terminal_background", lambda: None)
    monkeypatch.setattr(runner_module, "load_config", lambda: SimpleNamespace(theme="dark"))
    monkeypatch.setattr(runner_module, "install_sigint_interrupt", lambda _cb: (lambda: None))
    monkeypatch.setattr(runner_module, "settle_flicker_safe_stdout", _async_noop)
    monkeypatch.setattr(runner_module.ProgramStatusReporter, "from_terminal", classmethod(lambda cls: None))
    monkeypatch.setattr(runner_module.Session, "exists", staticmethod(lambda *a, **k: False))

    async def _main() -> None:
        # Instantiate the script lazily so it can capture the fake input.
        run_task = asyncio.create_task(runner_module._run_local_ui(fake_client.session_id))
        # Wait for the input provider to exist, then bind the script.
        for _ in range(200):
            if FakeInputProvider.instance is not None:
                break
            await asyncio.sleep(0.01)
        assert FakeInputProvider.instance is not None
        if setup is not None:
            await setup(fake_client)
        FakeInputProvider.instance.bind_script(script_factory(fake_client))
        await asyncio.wait_for(run_task, timeout=10.0)

    FakeInputProvider.instance = None

    # bind_script must run before iter_inputs is pulled; the runner awaits
    # input_provider.start() then iterates, so a tiny handshake is needed.
    _install_deferred_script(monkeypatch)
    asyncio.run(_main())
    return fake_client


async def _async_noop(*args: Any, **kwargs: Any) -> None:
    del args, kwargs


def _install_deferred_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make FakeInputProvider.iter_inputs wait until a script is bound."""

    original_iter = FakeInputProvider.iter_inputs

    def _patched(self: FakeInputProvider) -> AsyncGenerator[UserInputPayload]:
        async def _gen() -> AsyncGenerator[UserInputPayload]:
            for _ in range(500):
                if self._script is not None:
                    break
                await asyncio.sleep(0.01)
            assert self._script is not None
            async for item in self._script:
                yield item

        return _gen()

    monkeypatch.setattr(FakeInputProvider, "iter_inputs", _patched)
    del original_iter


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


# -- tests ------------------------------------------------------------------


def test_model_interaction_uses_typed_catalog_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []
    catalog_model = ModelCatalogEntry(
        selector="catalog-model@catalog-provider",
        model_name="catalog-model",
        provider="catalog-provider",
        model_id="upstream-model",
        model_alias=["catalog-alias"],
        params=["effort high"],
    )

    def select_one(*, items: list[Any], **kwargs: Any) -> str:
        captured.extend(items)
        return catalog_model.selector

    monkeypatch.setattr(runner_module, "select_one", select_one)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client._interaction_queue.put_nowait(
            events.UserInteractionRequestEvent(
                session_id=client.session_id,
                request_id="model",
                source="operation_model",
                payload=user_interaction.OperationSelectRequestPayload(
                    header="Model",
                    question="Select a model:",
                    options=[
                        user_interaction.OperationSelectOption(
                            id="__default__", label="Use default behavior", description="Inherit main model"
                        ),
                        user_interaction.OperationSelectOption(
                            id=catalog_model.selector, label=catalog_model.selector, description="", model=catalog_model
                        ),
                    ],
                ),
            )
        )
        for _ in range(100):
            if client.ops_of(op.UserInteractionRespondOperation):
                break
            await asyncio.sleep(0.01)
        yield UserInputPayload(text="exit")

    # The harness supplies only a local theme, with no local model configuration.
    client = run_scenario(monkeypatch, script)
    assert [item.value for item in captured] == ["__default__", None, catalog_model.selector]
    assert captured[1].selectable is False
    title = "".join(text for _style, text in captured[2].title)
    assert "upstream-model" in title
    assert "effort high" in title
    assert "catalog-alias" in captured[2].search_text
    response = client.ops_of(op.UserInteractionRespondOperation)[0].response
    assert isinstance(response.payload, user_interaction.OperationSelectResponsePayload)
    assert response.payload.selected_option_id == catalog_model.selector


@pytest.mark.parametrize("result", ["models", "empty", "error"])
def test_prompt_model_catalog_callback_uses_local_client_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    expected = ModelCatalog(
        models=[ModelCatalogEntry(selector="remote@provider", model_name="remote", provider="provider")], revision=4
    )

    async def get_catalog(self: FakeRuntimeClient) -> ModelCatalog:
        if result == "error":
            raise RuntimeError("catalog unavailable")
        return expected if result == "models" else ModelCatalog(models=[], revision=5)

    monkeypatch.setattr(FakeRuntimeClient, "get_model_catalog", get_catalog)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        provider = FakeInputProvider.instance
        assert provider is not None
        catalog = await provider.kwargs["get_model_catalog"]()
        assert catalog == expected if result == "models" else catalog is None
        yield UserInputPayload(text="exit")

    client = run_scenario(monkeypatch, script)
    notices = [event for event in client.local_events if isinstance(event, events.NoticeEvent)]
    if result == "models":
        assert not notices
    elif result == "empty":
        assert notices[0].content == "No models available."
    else:
        assert notices[0].is_error
        assert "catalog unavailable" in notices[0].content


@pytest.mark.parametrize("delivery", ["steering", "follow_up"])
def test_plain_message_echoes_and_starts_turn(
    monkeypatch: pytest.MonkeyPatch, delivery: Literal["steering", "follow_up"]
) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="hello world", delivery=delivery)
        await _settle()

    client = run_scenario(monkeypatch, script)

    assert [e.content for e in client.emitted_user_messages] == ["hello world"]
    run_ops = client.ops_of(op.RunAgentOperation)
    assert len(run_ops) == 1
    assert run_ops[0].input.text == "hello world"
    assert run_ops[0].input.delivery == delivery
    assert not client.ops_of(op.QueueFollowUpOperation)


def test_input_while_running_queues_steering(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="queued message")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    steering = client.ops_of(op.SteerAgentOperation)
    assert len(steering) == 1
    assert steering[0].input.text == "queued message"
    # No echo and no run op: the Runtime echoes queued messages when drained.
    assert client.emitted_user_messages == []
    assert client.ops_of(op.RunAgentOperation) == []


def test_follow_up_while_running_uses_separate_queue_and_preserves_split_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="steer now")
        await _settle()
        yield UserInputPayload(text="later one\n--- split ---\nlater two", delivery="follow_up", queued_edit=True)
        await _settle()
        provider = FakeInputProvider.instance
        assert provider is not None
        assert provider.pending_follow_ups == ("later one", "later two")
        assert await provider.dequeue_fn() == ("steer now", "later one", "later two")
        assert client.steering_texts() == client.follow_up_texts() == ()
        assert provider.pending_messages[-1] == provider.pending_follow_ups == ()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)
    queued = client.ops_of(op.QueueFollowUpOperation)
    assert [operation.input.text for operation in queued] == ["later one", "later two"]
    assert all(operation.input.delivery == "follow_up" for operation in queued)
    assert len(client.ops_of(op.SteerAgentOperation)) == 1
    assert not client.ops_of(op.RunAgentOperation) and not client.emitted_user_messages


def test_failed_follow_up_submission_rolls_back_its_mirror_only(monkeypatch: pytest.MonkeyPatch) -> None:
    original = FakeRuntimeClient.submit_and_wait

    async def submit(self: FakeRuntimeClient, operation: op.Operation) -> None:
        if isinstance(operation, op.QueueFollowUpOperation):
            raise RuntimeError("queue rejected")
        await original(self, operation)

    monkeypatch.setattr(FakeRuntimeClient, "submit_and_wait", submit)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="steer now")
        await _settle()
        yield UserInputPayload(text="later", delivery="follow_up")
        await _settle()
        assert client.follow_up_texts() == ()
        assert client.steering_texts() == ("steer now",)
        provider = FakeInputProvider.instance
        assert provider is not None and provider.pending_follow_ups == ()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)
    assert any(isinstance(event, events.NoticeEvent) and "later" in event.content for event in client.local_events)


@pytest.mark.parametrize("delivery", ["steering", "follow_up"])
def test_tasks_and_stop_immediately_while_busy_and_exit_closes_runtime(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, delivery: Literal["steering", "follow_up"]
) -> None:
    del isolated_home
    monkeypatch.setattr(
        FakeRuntimeClient,
        "command_agent",
        lambda *args, **kwargs: SimpleNamespace(session=SimpleNamespace(id="sess-1")),
    )

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        for text in ["/tasks", "/tasks output shell-1 0 512", "/tasks stop shell-1", "/tasks wait agent-1", "/stop"]:
            yield UserInputPayload(text=text, delivery=delivery)
            await _settle()
            assert client.is_running()
        yield UserInputPayload(text="exit")

    client = run_scenario(monkeypatch, script)
    assert [item.request.action for item in client.ops_of(op.ManageTasksOperation)] == [
        "output",
        "stop",
        "wait",
    ]
    assert [request.action for request in client.task_requests] == ["list"]
    assert len(client.ops_of(op.StopAllTasksOperation)) == 1
    assert client.ops_of(op.SteerAgentOperation) == []
    assert client.ops_of(op.QueueFollowUpOperation) == []
    assert client.ops_of(op.RunAgentOperation) == []
    assert client.ops_of(op.InterruptOperation) == []
    assert client.emitted_user_messages == []
    assert not client.is_running() and client.closed


def test_stop_while_idle_does_not_start_or_echo_a_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        FakeRuntimeClient,
        "command_agent",
        lambda *args, **kwargs: SimpleNamespace(session=SimpleNamespace(id="sess-1")),
    )

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="/stop")
        await _settle()
        assert not client.is_running()

    client = run_scenario(monkeypatch, script)
    assert len(client.ops_of(op.StopAllTasksOperation)) == 1
    assert not client.ops_of(op.RunAgentOperation) and not client.ops_of(op.SteerAgentOperation)
    assert not client.emitted_user_messages


def test_skill_invocation_while_running_queues_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/skill:name` only looks like a command: the Runtime expands it from the
    message body, so it must queue like any other text instead of being
    rejected as a client-dispatched command."""

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="/skill:commit 提交")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    steering = client.ops_of(op.SteerAgentOperation)
    assert len(steering) == 1
    # Queued verbatim: the skill token is resolved by the Runtime at drain time.
    assert steering[0].input.text == "/skill:commit 提交"
    notices = [e for e in client.local_events if isinstance(e, events.NoticeEvent)]
    assert not any("cannot be queued" in n.content for n in notices)


@pytest.mark.parametrize("delivery", ["steering", "follow_up"])
def test_command_while_running_is_rejected_with_notice(
    monkeypatch: pytest.MonkeyPatch, delivery: Literal["steering", "follow_up"]
) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="/compact", delivery=delivery)
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    assert client.ops_of(op.SteerAgentOperation) == []
    assert client.ops_of(op.QueueFollowUpOperation) == []
    notices = [e for e in client.local_events if isinstance(e, events.NoticeEvent)]
    assert any("cannot be queued" in n.content for n in notices)


def test_follow_up_btw_still_dispatches_side_question_while_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        FakeRuntimeClient,
        "command_agent",
        lambda self: SimpleNamespace(session=SimpleNamespace(id=self.session_id)),
    )

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="/btw why?", delivery="follow_up")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)
    assert [operation.question for operation in client.ops_of(op.AskSideQuestionOperation)] == ["why?"]
    assert not client.ops_of(op.QueueFollowUpOperation) and not client.ops_of(op.SteerAgentOperation)
    assert not client.ops_of(op.RunAgentOperation) and not client.emitted_user_messages


@pytest.mark.parametrize("running_status_lags", [False, True])
def test_esc_submits_interrupt_with_retraction_and_prefill(
    monkeypatch: pytest.MonkeyPatch, running_status_lags: bool
) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_active_operation("turn-1")
        # Let the watcher install the interrupt handler.
        for _ in range(100):
            await asyncio.sleep(0.01)
            provider = FakeInputProvider.instance
            if provider is not None and provider.interrupt_handler is not None:
                break
        provider = FakeInputProvider.instance
        assert provider is not None and provider.interrupt_handler is not None
        provider.interrupt_handler()
        await _settle()
        await asyncio.sleep(0.05)
        # Runtime winds down the turn and retracts the message.
        client.set_prefill("interrupted text")
        if running_status_lags:
            # InterruptEvent clears the operation before execution becomes idle.
            client._active_operation_id = None
            await _settle()
            assert client.is_running()
            assert provider.prefills == []
        client.set_running(False)
        # Give the watcher time to flip to idle and apply the prefill.
        for _ in range(100):
            await asyncio.sleep(0.01)
            if provider.prefills:
                break
        yield UserInputPayload(text="")  # keep the loop alive one beat
        await _settle()

    client = run_scenario(monkeypatch, script)

    interrupts = client.ops_of(op.InterruptOperation)
    assert len(interrupts) == 1
    assert interrupts[0].expected_operation_id == "turn-1"
    assert interrupts[0].retract_unanswered_input is True
    assert interrupts[0].resume_follow_ups is True
    provider = FakeInputProvider.instance
    assert provider is not None
    assert "interrupted text" in provider.prefills
    # The running flag must clear BEFORE the prefill is applied: the real
    # prompt layer refuses to restart the prompt while the agent looks busy,
    # so the reversed order shelves the text until after the NEXT turn.
    prefill_index = provider.call_log.index(("prefill", "interrupted text"))
    running_cleared_index = provider.call_log.index(("agent_running", False))
    assert running_cleared_index < prefill_index


def test_esc_skips_retraction_when_input_box_has_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in the input box blocks the prefill, so the retraction must not run.

    Retracting anyway drops the interrupted message: the prompt layer refuses
    to overwrite what the user typed, and the withdrawn text is gone.
    """

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_active_operation("turn-1")
        for _ in range(100):
            await asyncio.sleep(0.01)
            provider = FakeInputProvider.instance
            if provider is not None and provider.interrupt_handler is not None:
                break
        provider = FakeInputProvider.instance
        assert provider is not None and provider.interrupt_handler is not None
        # The user typed a follow-up while the turn was running.
        provider.input_text = "half-written follow-up"
        provider.interrupt_handler()
        await _settle()
        await asyncio.sleep(0.05)
        client.set_running(False)
        yield UserInputPayload(text="")
        await _settle()

    client = run_scenario(monkeypatch, script)

    interrupts = client.ops_of(op.InterruptOperation)
    assert len(interrupts) == 1
    assert interrupts[0].retract_unanswered_input is False
    provider = FakeInputProvider.instance
    assert provider is not None
    assert provider.prefills == []


def test_esc_latch_clears_when_queue_starts_before_idle_is_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_active_operation("turn-1")
        provider = FakeInputProvider.instance
        assert provider is not None
        for _ in range(100):
            await asyncio.sleep(0.01)
            if provider.interrupt_handler is not None:
                break
        assert provider.interrupt_handler is not None
        provider.interrupt_handler()
        await _settle()

        # InterruptEvent(false) and the drained queue's TaskStart(true) were
        # coalesced before the watcher ran; only the operation identity changed.
        client.set_active_operation("queued-turn")
        for _ in range(100):
            await asyncio.sleep(0.01)
            provider.interrupt_handler()
            if len(client.ops_of(op.InterruptOperation)) == 2:
                break
        client.set_running(False)
        yield UserInputPayload(text="")
        await _settle()

    client = run_scenario(monkeypatch, script)
    interrupts = client.ops_of(op.InterruptOperation)
    assert [item.expected_operation_id for item in interrupts] == ["turn-1", "queued-turn"]


@pytest.mark.parametrize("exit_input", ["exit", "quit", ":q", "/exit", "/ex", " /exit "])
@pytest.mark.parametrize("running", [True, False])
def test_exit_closes_runtime_without_queueing(monkeypatch: pytest.MonkeyPatch, exit_input: str, running: bool) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(running)
        await _settle()
        yield UserInputPayload(text=exit_input)
        pytest.fail("The runner must stop reading input immediately after exit")

    client = run_scenario(monkeypatch, script)

    assert client.closed is True
    assert not client.is_running()
    assert client.submitted == []
    assert client.steering_texts() == ()
    assert client.emitted_user_messages == []
    assert client.local_events == []


def test_idle_queue_edit_splits_first_runs_rest_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="first message\n---\nsecond message", queued_edit=True)
        await _settle()

    client = run_scenario(monkeypatch, script)

    run_ops = client.ops_of(op.RunAgentOperation)
    steering = client.ops_of(op.SteerAgentOperation)
    assert len(run_ops) == 1
    assert run_ops[0].input.text == "first message"
    assert len(steering) == 1
    assert steering[0].input.text == "second message"


def test_bash_input_submits_run_bash(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="!echo hi")
        await _settle()

    client = run_scenario(monkeypatch, script)

    bash_ops = client.ops_of(op.RunBashOperation)
    assert len(bash_ops) == 1
    assert bash_ops[0].command == "echo hi"
    assert [e.content for e in client.emitted_user_messages] == ["!echo hi"]


def test_new_command_creates_and_switches_session(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    def _fake_create(**kwargs: Any) -> str:
        created.append(kwargs)
        return "new-session-id"

    async def create_session(self: FakeRuntimeClient) -> str:
        return _fake_create(work_dir=Path("/nonexistent-work-dir"), model=self._info.model_config_name)

    monkeypatch.setattr(FakeRuntimeClient, "create_session", create_session)

    class _FakeCommandAgent:
        def __init__(self, session_id: str, work_dir: Path, *, load_history: bool = True) -> None:
            del load_history
            self.session = SimpleNamespace(id=session_id, work_dir=work_dir)

        @property
        def profile(self) -> None:
            return None

    monkeypatch.setattr(
        FakeRuntimeClient,
        "command_agent",
        lambda self: _FakeCommandAgent(self.session_id, Path("/nonexistent-work-dir")),
    )

    async def _fake_dispatch(user_input: UserInputPayload, agent: Any, *, submission_id: str) -> Any:
        del agent, submission_id
        assert user_input.text == "/new"
        from klaude_code.tui.command.command_abc import CommandResult

        return CommandResult(operations=[op.ClearSessionOperation(session_id="sess-1")])

    monkeypatch.setattr(runner_module, "dispatch_command", _fake_dispatch)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="/new")
        await _settle()

    client = run_scenario(monkeypatch, script)

    assert client.switched_to == ["new-session-id"]
    assert created and created[0]["model"] is None


def test_dequeue_pending_messages_returns_runtime_confirmed_pop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="msg one")
        await _settle()
        yield UserInputPayload(text="msg later", delivery="follow_up")
        await _settle()
        provider = FakeInputProvider.instance
        assert provider is not None
        texts = await provider.dequeue_fn()
        assert texts == ("msg one", "msg later")
        assert client.steering_texts() == client.follow_up_texts() == ()
        assert provider.pending_messages[-1] == provider.pending_follow_ups == ()
        await _settle()
        await asyncio.sleep(0.05)
        client.set_running(False)

    client = run_scenario(monkeypatch, script)
    assert client.dequeue_calls == 1


def test_esc_then_type_waits_for_wind_down_then_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        for _ in range(100):
            await asyncio.sleep(0.01)
            provider = FakeInputProvider.instance
            if provider is not None and provider.interrupt_handler is not None:
                break
        provider = FakeInputProvider.instance
        assert provider is not None and provider.interrupt_handler is not None
        provider.interrupt_handler()
        await _settle()

        # Wind the turn down shortly after the corrected input lands.
        async def _wind_down() -> None:
            await asyncio.sleep(0.1)
            client.set_running(False)

        wind_down = asyncio.create_task(_wind_down())
        yield UserInputPayload(text="corrected instruction")
        with contextlib.suppress(Exception):
            await wind_down
        await _settle()

    client = run_scenario(monkeypatch, script)

    run_ops = client.ops_of(op.RunAgentOperation)
    assert len(run_ops) == 1
    assert run_ops[0].input.text == "corrected instruction"
    # The corrected input started a fresh turn instead of being queued.
    assert client.ops_of(op.SteerAgentOperation) == []


def test_esc_prefill_lands_before_interrupted_op_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interrupted op's finish trails its wind-down (slow provider stream
    close); the prefill and idle prompt must not wait seconds for it."""

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.hold_run_ops = True
        yield UserInputPayload(text="task to interrupt")
        await _settle()
        client.set_running(True)
        provider = FakeInputProvider.instance
        assert provider is not None
        for _ in range(100):
            await asyncio.sleep(0.01)
            if provider.interrupt_handler is not None:
                break
        assert provider.interrupt_handler is not None
        provider.interrupt_handler()
        await _settle()
        await asyncio.sleep(0.05)

        # Runtime confirms the interrupt; the run op stays unfinished (gate).
        client.set_prefill("interrupted text")
        client.set_running(False)
        for _ in range(100):
            await asyncio.sleep(0.01)
            if provider.prefills:
                break
        # Applied while the operation is still formally in flight.
        assert "interrupted text" in provider.prefills
        client.release_operations()
        await _settle()

    client = run_scenario(monkeypatch, script)
    provider = FakeInputProvider.instance
    assert provider is not None
    assert "interrupted text" in provider.prefills
    assert client.ops_of(op.InterruptOperation)


def test_late_retract_prefill_still_lands(monkeypatch: pytest.MonkeyPatch) -> None:
    """A retraction that arrives after the idle transition (Runtime stalled
    mid-batch) must still reach the input box instead of being shelved."""

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        provider = FakeInputProvider.instance
        assert provider is not None
        for _ in range(100):
            await asyncio.sleep(0.01)
            if provider.interrupt_handler is not None:
                break
        assert provider.interrupt_handler is not None
        provider.interrupt_handler()
        await _settle()
        await asyncio.sleep(0.05)

        # Interrupt confirmed with NO prefill yet: the transition runs empty.
        client.set_running(False)
        await asyncio.sleep(0.1)
        # The retraction trails in a later batch.
        client.set_prefill("late retract text")
        for _ in range(100):
            await asyncio.sleep(0.01)
            if "late retract text" in provider.prefills:
                break
        yield UserInputPayload(text="")  # keep the loop alive one beat
        await _settle()

    run_scenario(monkeypatch, script)
    provider = FakeInputProvider.instance
    assert provider is not None
    assert "late retract text" in provider.prefills


@pytest.mark.parametrize("already_closed", [False, True])
def test_remote_resolution_closes_question_without_submitting_again(
    monkeypatch: pytest.MonkeyPatch, already_closed: bool
) -> None:
    opened, exited = Event(), Event()

    def select_questions(*, closed: Event, **kwargs: Any) -> None:
        opened.set()
        assert closed.wait(3)
        exited.set()

    monkeypatch.setattr(runner_module, "select_questions", select_questions)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        if already_closed:
            client.interaction_closed.set()
        client._interaction_queue.put_nowait(
            events.UserInteractionRequestEvent(
                session_id=client.session_id,
                request_id="question",
                source="tool",
                payload=user_interaction.AskUserQuestionRequestPayload(questions=[]),
            )
        )
        if not already_closed:
            assert await asyncio.to_thread(opened.wait, 2)
            client.interaction_closed.set()
            assert await asyncio.to_thread(exited.wait, 2)
        await _settle()
        yield UserInputPayload(text="exit")

    client = run_scenario(monkeypatch, script)
    assert client.ops_of(op.UserInteractionRespondOperation) == []
    assert opened.is_set() is not already_closed


@pytest.mark.parametrize("confirm", [True, False])
def test_local_exit_confirms_owned_background_tasks(monkeypatch: pytest.MonkeyPatch, confirm: bool) -> None:
    choices: list[bool] = []
    reached_after_cancel = []

    def choose(*, items: list[SelectItem[bool]], use_search_filter: bool, **_kwargs: Any) -> bool:
        assert use_search_filter is False
        tokens = _build_choices_tokens(items, list(range(len(items))), 0, "→")
        lines = "".join(text for _, text in tokens).splitlines()
        assert [line.strip() for line in lines] == ["→ Keep working", "Stop tasks and exit"]
        choices.append(confirm)
        return confirm

    monkeypatch.setattr(runner_module, "select_one", choose)

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.owned_tasks_running = True
        yield UserInputPayload(text="exit")
        if confirm:
            pytest.fail("Confirmed exit must stop reading input")
        reached_after_cancel.append(True)
        client.owned_tasks_running = False
        yield UserInputPayload(text="exit")

    client = run_scenario(
        monkeypatch,
        script,
    )
    assert choices == [confirm]
    assert reached_after_cancel == ([] if confirm else [True])
    assert client.closed


@pytest.mark.parametrize("command", ["/new", "/fork-session", "/fork-s", "/rewind"])
def test_local_switch_commands_refuse_owned_background_tasks(monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.owned_tasks_running = True
        yield UserInputPayload(text=command)
        client.owned_tasks_running = False
        yield UserInputPayload(text="exit")

    client = run_scenario(
        monkeypatch,
        script,
    )
    assert not client.submitted
    assert not client.emitted_user_messages
    assert any(isinstance(event, events.NoticeEvent) and "/stop" in event.content for event in client.local_events)
