"""Runner behavior tests against an in-memory RuntimeClient fake.

`run_attach` is exercised end to end with fakes injected for the socket
client, the prompt-toolkit input layer, and the display. These cover the
client-side semantics that survived the server split: echo + turn
submission, queueing while busy, Esc interrupt + prefill, detach-on-exit,
and /new reattach. Queue draining itself now lives on the server (see
tests/server/test_ws_attach_replay.py).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import klaude_code.tui.runner as runner_module
from klaude_code.protocol import events, op
from klaude_code.protocol.message import UserInputPayload
from klaude_code.tui.client import ClientConnectionError
from klaude_code.tui.client.base import SessionInfoSnapshot

# -- fakes ------------------------------------------------------------------


class FakeRuntimeClient:
    def __init__(self, session_id: str = "sess-1") -> None:
        self._session_id = session_id
        self.submitted: list[op.Operation] = []
        self.emitted_user_messages: list[events.UserMessageEvent] = []
        self.local_events: list[events.Event] = []
        self.reattached_to: list[str] = []
        self.closed = False
        self.dequeue_calls = 0
        self.hold_run_ops = False

        self._info = SessionInfoSnapshot(session_id=session_id, work_dir="/nonexistent-work-dir")
        self._running = False
        self._follow_ups: list[str] = []
        self._state_changed = asyncio.Event()
        self._connection_lost = asyncio.Event()
        self._interaction_queue: asyncio.Queue[events.UserInteractionRequestEvent] = asyncio.Queue()
        self._interrupt_prefill: str | None = None
        self._blocked_ops: dict[str, asyncio.Event] = {}

    # test controls
    def set_running(self, running: bool) -> None:
        self._running = running
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

    async def close(self) -> None:
        self.closed = True

    async def reattach(self, session_id: str) -> None:
        self.reattached_to.append(session_id)
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
        if isinstance(operation, op.FollowUpAgentOperation):
            self._follow_ups.append(operation.input.text)
            self._info.follow_ups = tuple(self._follow_ups)
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

    async def dequeue_follow_ups(self) -> tuple[str, ...]:
        self.dequeue_calls += 1
        texts = tuple(self._follow_ups)
        self._follow_ups.clear()
        self._info.follow_ups = ()
        self._state_changed.set()
        return texts

    def is_running(self) -> bool:
        return self._running

    def follow_up_texts(self) -> tuple[str, ...]:
        return self._info.follow_ups

    def optimistically_append_follow_ups(self, texts: Sequence[str]) -> None:
        self._info.follow_ups = (*self._info.follow_ups, *texts)
        self._state_changed.set()

    def remove_optimistic_follow_up(self, text: str) -> None:
        follow_ups = list(self._info.follow_ups)
        for idx in range(len(follow_ups) - 1, -1, -1):
            if follow_ups[idx] == text:
                del follow_ups[idx]
                break
        self._info.follow_ups = tuple(follow_ups)
        self._state_changed.set()

    def session_info(self) -> SessionInfoSnapshot:
        return self._info

    def consume_interrupt_prefill(self) -> str | None:
        text = self._interrupt_prefill
        self._interrupt_prefill = None
        return text

    def state_changed_event(self) -> asyncio.Event:
        return self._state_changed

    def connection_lost_event(self) -> asyncio.Event:
        return self._connection_lost

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

    def set_pending_messages(self, messages: tuple[str, ...]) -> None:
        self.pending_messages.append(messages)

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

    def set_dequeue_pending_messages(self, fn: Callable[[], tuple[str, ...]]) -> None:
        self.dequeue_fn = fn

    async def pause_for_external_input(self) -> Callable[[], None]:
        return lambda: None


class FakeDisplay:
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

    monkeypatch.setattr(runner_module, "SocketRuntimeClient", lambda *a, **k: fake_client)
    monkeypatch.setattr(runner_module, "PromptToolkitInput", FakeInputProvider)
    monkeypatch.setattr(runner_module, "TUIDisplay", FakeDisplay)
    monkeypatch.setattr(runner_module, "update_terminal_title", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "configure_pt_theme", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "is_light_terminal_background", lambda: None)
    monkeypatch.setattr(runner_module, "load_config", lambda: SimpleNamespace(theme="dark"))
    monkeypatch.setattr(runner_module, "install_sigint_interrupt", lambda _cb: (lambda: None))
    monkeypatch.setattr(runner_module, "settle_flicker_safe_stdout", _async_noop)
    monkeypatch.setattr(runner_module, "start_prevent_sleep", lambda: None)
    monkeypatch.setattr(runner_module, "stop_prevent_sleep", lambda: None)
    monkeypatch.setattr(runner_module, "force_stop_prevent_sleep", lambda: None)
    monkeypatch.setattr(
        runner_module,
        "build_welcome_context_event",
        lambda **kwargs: events.WelcomeContextEvent(session_id=kwargs["session_id"], work_dir="."),
    )
    monkeypatch.setattr(runner_module.HerdrReporter, "from_env", classmethod(lambda cls: None))
    monkeypatch.setattr(runner_module.Session, "exists", staticmethod(lambda *a, **k: False))

    async def _main() -> None:
        # Instantiate the script lazily so it can capture the fake input.
        run_task = asyncio.create_task(runner_module.run_attach(fake_client.session_id))
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


def test_plain_message_echoes_and_starts_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="hello world")
        await _settle()

    client = run_scenario(monkeypatch, script)

    assert [e.content for e in client.emitted_user_messages] == ["hello world"]
    run_ops = client.ops_of(op.RunAgentOperation)
    assert len(run_ops) == 1
    assert run_ops[0].input.text == "hello world"


def test_input_while_running_queues_follow_up(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="queued message")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    follow_ups = client.ops_of(op.FollowUpAgentOperation)
    assert len(follow_ups) == 1
    assert follow_ups[0].input.text == "queued message"
    # No echo and no run op: the server echoes queued messages when drained.
    assert client.emitted_user_messages == []
    assert client.ops_of(op.RunAgentOperation) == []


def test_failed_queue_submit_rolls_back_mirror_with_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    """A queued submit the server never accepted must not linger in the
    mirror as forever-pending; it rolls back and the user is told."""

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        original_submit = client.submit

        async def _failing_submit(operation: op.Operation) -> str:
            if isinstance(operation, op.FollowUpAgentOperation):
                raise ClientConnectionError("connection to klaude server lost")
            return await original_submit(operation)

        client.submit = _failing_submit  # type: ignore[method-assign]
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="lost message")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    assert client.follow_up_texts() == ()
    notices = [e for e in client.local_events if isinstance(e, events.NoticeEvent)]
    assert any("could not be queued" in n.content for n in notices)
    assert any("lost message" in n.content for n in notices)


def test_command_while_running_is_rejected_with_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="/compact")
        await _settle()
        client.set_running(False)

    client = run_scenario(monkeypatch, script)

    assert client.ops_of(op.FollowUpAgentOperation) == []
    notices = [e for e in client.local_events if isinstance(e, events.NoticeEvent)]
    assert any("cannot be queued" in n.content for n in notices)


def test_esc_submits_interrupt_with_retraction_and_prefill(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
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
        # Server winds down the turn and retracts the message.
        client.set_prefill("interrupted text")
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


def test_exit_while_running_detaches_without_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="exit")

    client = run_scenario(monkeypatch, script)

    assert client.closed is True
    assert client.ops_of(op.InterruptOperation) == []


def test_idle_queue_edit_splits_first_runs_rest_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="first message\n---\nsecond message", queued_edit=True)
        await _settle()

    client = run_scenario(monkeypatch, script)

    run_ops = client.ops_of(op.RunAgentOperation)
    follow_ups = client.ops_of(op.FollowUpAgentOperation)
    assert len(run_ops) == 1
    assert run_ops[0].input.text == "first message"
    assert len(follow_ups) == 1
    assert follow_ups[0].input.text == "second message"


def test_bash_input_submits_run_bash(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="!echo hi")
        await _settle()

    client = run_scenario(monkeypatch, script)

    bash_ops = client.ops_of(op.RunBashOperation)
    assert len(bash_ops) == 1
    assert bash_ops[0].command == "echo hi"
    assert [e.content for e in client.emitted_user_messages] == ["!echo hi"]


def test_peek_mode_rejects_input(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeRuntimeClient()

    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="hello")
        await _settle()

    monkeypatch.setattr(runner_module, "SocketRuntimeClient", lambda *a, **k: fake_client)
    monkeypatch.setattr(runner_module, "PromptToolkitInput", FakeInputProvider)
    monkeypatch.setattr(runner_module, "TUIDisplay", FakeDisplay)
    monkeypatch.setattr(runner_module, "update_terminal_title", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "configure_pt_theme", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "is_light_terminal_background", lambda: None)
    monkeypatch.setattr(runner_module, "load_config", lambda: SimpleNamespace(theme="dark"))
    monkeypatch.setattr(runner_module, "install_sigint_interrupt", lambda _cb: (lambda: None))
    monkeypatch.setattr(runner_module, "settle_flicker_safe_stdout", _async_noop)
    monkeypatch.setattr(runner_module, "start_prevent_sleep", lambda: None)
    monkeypatch.setattr(runner_module, "stop_prevent_sleep", lambda: None)
    monkeypatch.setattr(runner_module, "force_stop_prevent_sleep", lambda: None)
    monkeypatch.setattr(
        runner_module,
        "build_welcome_context_event",
        lambda **kwargs: events.WelcomeContextEvent(session_id=kwargs["session_id"], work_dir="."),
    )
    monkeypatch.setattr(runner_module.HerdrReporter, "from_env", classmethod(lambda cls: None))
    monkeypatch.setattr(runner_module.Session, "exists", staticmethod(lambda *a, **k: False))
    _install_deferred_script(monkeypatch)

    async def _main() -> None:
        FakeInputProvider.instance = None
        run_task = asyncio.create_task(runner_module.run_attach(fake_client.session_id, peek=True))
        for _ in range(200):
            if FakeInputProvider.instance is not None:
                break
            await asyncio.sleep(0.01)
        assert FakeInputProvider.instance is not None
        FakeInputProvider.instance.bind_script(script(fake_client))
        await asyncio.wait_for(run_task, timeout=10.0)

    asyncio.run(_main())

    assert fake_client.emitted_user_messages == []
    assert fake_client.ops_of(op.RunAgentOperation) == []
    notices = [e for e in fake_client.local_events if isinstance(e, events.NoticeEvent)]
    assert any("Read-only" in n.content for n in notices)


def test_new_command_creates_and_reattaches(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    def _fake_create(**kwargs: Any) -> str:
        created.append(kwargs)
        return "new-session-id"

    monkeypatch.setattr(
        "klaude_code.tui.client.server_api.create_server_session",
        _fake_create,
    )

    class _FakeCommandAgent:
        def __init__(self, session_id: str, work_dir: Path, *, load_history: bool = True) -> None:
            del load_history
            self.session = SimpleNamespace(id=session_id, work_dir=work_dir)

        @property
        def profile(self) -> None:
            return None

    monkeypatch.setattr(runner_module, "ClientCommandAgent", _FakeCommandAgent)

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

    assert client.reattached_to == ["new-session-id"]
    assert created and created[0]["model"] is None


def test_dequeue_pending_messages_returns_server_confirmed_pop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        client.set_running(True)
        await _settle()
        yield UserInputPayload(text="msg one")
        await _settle()
        provider = FakeInputProvider.instance
        assert provider is not None
        texts = await provider.dequeue_fn()
        assert texts == ("msg one",)
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
    assert client.ops_of(op.FollowUpAgentOperation) == []


def test_connection_lost_exits_input_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def script(client: FakeRuntimeClient) -> AsyncGenerator[UserInputPayload]:
        yield UserInputPayload(text="hello before loss")
        await _settle()
        client.connection_lost_event().set()
        await _settle()
        # A dead connection: this input must be dropped, not submitted.
        yield UserInputPayload(text="typed after loss")
        await _settle()

    client = run_scenario(monkeypatch, script)

    submitted_texts = [item.input.text for item in client.ops_of(op.RunAgentOperation)]
    assert submitted_texts == ["hello before loss"]
    provider = FakeInputProvider.instance
    assert provider is not None
    # The connection watcher asked the prompt layer to end the input loop.
    assert provider.exit_requests >= 1
    assert client.closed is True


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

        # Server confirms the interrupt; the run op stays unfinished (gate).
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
    """A retraction that arrives after the idle transition (server stalled
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
