"""Interactive TUI runner: a WebSocket client of the local klaude server.

The TUI no longer embeds a runtime. ``run_attach`` connects to the single
local server (UDS WS), replays the session, and follows live. Every exit
path is a detach: the server keeps the session and any running task alive.

Structure:
- ``SocketRuntimeClient`` owns the wire, the display feed, and state mirrors.
- A watcher task drives the prompt's busy state, Esc interrupt handling,
  interrupt prefill, and the queued-message list from client mirrors —
  turns started by other clients or by the server's follow-up drain are
  reflected exactly like locally started ones.
- Follow-up queueing and draining live on the server; typing while the
  agent runs sends a FollowUpAgentOperation.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sys
from collections.abc import AsyncGenerator, Callable, Coroutine
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from klaude_code.agent.runtime.away_summary import AwaySummaryCoordinator
from klaude_code.agent.welcome_context import build_welcome_context_event
from klaude_code.app.herdr import HerdrReporter
from klaude_code.config import load_config
from klaude_code.log import DebugType, log, log_debug
from klaude_code.protocol import events, op, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.protocol.models import SessionRuntimeState
from klaude_code.session.session import Session
from klaude_code.tui.client import RuntimeClient, SessionInfoSnapshot, SocketRuntimeClient
from klaude_code.tui.client.command_agent import ClientCommandAgent
from klaude_code.tui.command import (
    dispatch_command,
    get_command_info_list,
    has_background_command,
    has_interactive_command,
)
from klaude_code.tui.command.command_abc import CommandResult
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input.flicker_safe_stdout import settle_flicker_safe_stdout
from klaude_code.tui.input.key_bindings import has_explicit_queued_message_separator, split_queued_message_edit_text
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput
from klaude_code.tui.input.pt_theme import CLASS_TOOL_RESULT, configure_pt_theme
from klaude_code.tui.terminal.color import is_light_terminal_background
from klaude_code.tui.terminal.control import install_sigint_interrupt
from klaude_code.tui.terminal.prevent_sleep import force_stop_prevent_sleep, start_prevent_sleep, stop_prevent_sleep
from klaude_code.tui.terminal.selector import (
    DEFAULT_PICKER_STYLE,
    QuestionPrompt,
    SelectItem,
    build_model_select_items,
    select_one,
    select_questions,
)
from klaude_code.tui.terminal.title import update_terminal_title


def _split_queue_edit_payload(user_input: UserInputPayload) -> tuple[UserInputPayload, ...]:
    if user_input.images:
        return (user_input,)
    should_split = user_input.queued_edit or has_explicit_queued_message_separator(user_input.text)
    if not should_split:
        return (user_input,)
    parts = split_queued_message_edit_text(user_input.text)
    if len(parts) == 1:
        return (user_input,)
    return tuple(UserInputPayload(text=text) for text in parts)


def _is_exit_input(text: str) -> bool:
    return text.strip().lower() in {"exit", ":q", "quit"}


def _is_command_shaped(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("/", "!", "！"))


async def run_attach(session_id: str, *, peek: bool = False) -> None:
    """Attach the interactive TUI to a server-side session."""

    update_terminal_title()

    cfg = load_config()
    theme: str | None = cfg.theme
    if theme is None:
        detected = is_light_terminal_background()
        if detected is True:
            theme = "light"
        elif detected is False:
            theme = "dark"
    configure_pt_theme(theme)

    input_provider: PromptToolkitInput | None = None

    def _set_prompt_suggestion(text: str | None) -> None:
        if input_provider is not None:
            input_provider.set_prompt_suggestion(text)

    def _set_status_lines(
        lines: tuple[PromptStatusLine, ...],
        separator_text: str | None = None,
        reset_bottom_height: bool = False,
    ) -> None:
        if input_provider is not None:
            input_provider.set_status_lines(
                lines,
                separator_text=separator_text,
                reset_bottom_height=reset_bottom_height,
            )

    def _set_stream_lines(
        lines: tuple[str, ...],
        end_of_stream: bool = False,
        style_class: str = CLASS_TOOL_RESULT,
    ) -> None:
        if input_provider is not None:
            input_provider.set_stream_lines(
                lines,
                end_of_stream=end_of_stream,
                style_class=style_class,
            )

    tui_display = TUIDisplay(
        theme=theme,
        on_prompt_suggestion=_set_prompt_suggestion,
        on_status_update=_set_status_lines,
        on_stream_update=_set_stream_lines,
    )

    prevent_sleep_active = False

    def _start_prevent_sleep_if_needed() -> None:
        nonlocal prevent_sleep_active
        if prevent_sleep_active:
            return
        start_prevent_sleep()
        prevent_sleep_active = True

    def _stop_prevent_sleep_if_needed() -> bool:
        nonlocal prevent_sleep_active
        if not prevent_sleep_active:
            return False
        stop_prevent_sleep()
        prevent_sleep_active = False
        return True

    herdr = HerdrReporter.from_env()
    local_turn_ops: set[str] = set()

    # -- interaction pickers (terminal UI, unchanged from the in-process era) --

    def _build_question_items(
        question: user_interaction.AskUserQuestionQuestion,
    ) -> list[SelectItem[str]]:
        import textwrap

        columns = shutil.get_terminal_size((120, 24)).columns
        # 7 = pointer_pad (3) + description indent (4)
        desc_width = max(30, columns - 7)
        items: list[SelectItem[str]] = []
        for idx, option in enumerate(question.options, start=1):
            desc_lines = textwrap.wrap(option.description, width=desc_width, max_lines=5, placeholder=" ...")
            desc_text = "\n".join(f"    {line}" for line in desc_lines) + "\n"
            title: list[tuple[str, str]] = [
                ("class:msg", f"{idx}. {option.label}\n"),
                ("class:meta", desc_text),
            ]
            items.append(
                SelectItem(
                    title=title,
                    value=option.id,
                    search_text=f"{option.label} {option.description}",
                    summary=option.label,
                    markdown=option.markdown,
                )
            )
        return items

    def _build_operation_select_items(
        payload: user_interaction.OperationSelectRequestPayload,
    ) -> list[SelectItem[str]]:
        items: list[SelectItem[str]] = []
        for idx, option in enumerate(payload.options, start=1):
            title: list[tuple[str, str]] = [("class:msg", f"{idx}. {option.label}\n")]
            if option.description:
                title.append(("class:meta", f"    {option.description}\n"))
            items.append(
                SelectItem(
                    title=title,
                    value=option.id,
                    search_text=f"{option.label} {option.description}",
                    summary=option.label,
                )
            )
        return items

    def _pick_model_with_model_picker_style(payload: user_interaction.OperationSelectRequestPayload) -> str | None:
        if not payload.options:
            return None

        valid_ids = {opt.id for opt in payload.options}

        config = load_config()
        entries = [
            m for m in config.iter_model_entries(only_available=True, include_disabled=False) if m.selector in valid_ids
        ]
        model_selectors = {m.selector for m in entries}

        items = build_model_select_items(entries)

        special_opts = [opt for opt in payload.options if opt.id not in model_selectors]
        for opt in reversed(special_opts):
            title: list[tuple[str, str]] = [("class:msg", opt.label)]
            if opt.description:
                title.append(("class:meta", f"  {opt.description}"))
            title.append(("class:meta", "\n"))
            items.insert(
                0,
                SelectItem(
                    title=title,
                    value=opt.id,
                    search_text=f"{opt.label} {opt.description}",
                ),
            )

        selected = select_one(
            message=payload.question,
            items=items,
            pointer="→",
            use_search_filter=True,
            initial_search_text=payload.initial_search_text,
            style=DEFAULT_PICKER_STYLE(),
        )
        return selected if isinstance(selected, str) else None

    def _pick_option_with_selector_style(payload: user_interaction.OperationSelectRequestPayload) -> str | None:
        selected = select_one(
            message=payload.question,
            items=_build_operation_select_items(payload),
            pointer="→",
            use_search_filter=True,
            initial_search_text=payload.initial_search_text,
            style=DEFAULT_PICKER_STYLE(),
        )
        return selected if isinstance(selected, str) else None

    def _submitted_single_choice_response(
        *,
        selected_option_id: str,
    ) -> user_interaction.UserInteractionResponse:
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.OperationSelectResponsePayload(
                selected_option_id=selected_option_id,
            ),
        )

    async def _pause_repl_for_external_input() -> Callable[[], None]:
        if input_provider is not None:
            return await input_provider.pause_for_external_input()
        return lambda: None

    async def _collect_interaction_response(
        request_event: events.UserInteractionRequestEvent,
    ) -> user_interaction.UserInteractionResponse:
        payload = request_event.payload
        if isinstance(payload, user_interaction.OperationSelectRequestPayload):
            resume_repl = await _pause_repl_for_external_input()
            restore_progress_ui = _agent_busy()
            tui_display.hide_progress_ui()
            was_preventing_sleep = _stop_prevent_sleep_if_needed()

            try:
                if request_event.source == "operation_model":
                    selected = await asyncio.to_thread(_pick_model_with_model_picker_style, payload)
                else:
                    selected = await asyncio.to_thread(_pick_option_with_selector_style, payload)
            finally:
                resume_repl()
                if was_preventing_sleep:
                    _start_prevent_sleep_if_needed()

            if selected is None:
                return user_interaction.UserInteractionResponse(status="cancelled", payload=None)
            if restore_progress_ui:
                tui_display.show_progress_ui()
            return _submitted_single_choice_response(selected_option_id=selected)

        if not isinstance(payload, user_interaction.AskUserQuestionRequestPayload):
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        answers: list[user_interaction.AskUserQuestionAnswer] = []
        if request_event.source == "tool":
            tui_display.notify_ask_user_question(
                question_count=len(payload.questions),
                headers=[q.header for q in payload.questions],
            )
        resume_repl = await _pause_repl_for_external_input()
        tui_display.hide_progress_ui(flush_open_blocks=False)
        was_preventing_sleep = _stop_prevent_sleep_if_needed()

        prompts: list[QuestionPrompt[str]] = []
        for question in payload.questions:
            prompts.append(
                QuestionPrompt(
                    header=question.header,
                    message=question.question,
                    items=_build_question_items(question),
                    multi_select=question.multi_select,
                    input_placeholder=question.input_placeholder or "Type something.",
                    other_value="__other__",
                )
            )

        try:
            selections = await asyncio.to_thread(
                lambda: select_questions(
                    questions=prompts,
                    pointer="→",
                    style=DEFAULT_PICKER_STYLE(),
                )
            )
        finally:
            resume_repl()
            if was_preventing_sleep:
                _start_prevent_sleep_if_needed()

        if selections is None:
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        for question, selection in zip(payload.questions, selections, strict=False):
            note_text = selection.input_text.strip()
            selected_ids = list(selection.selected_values)
            if note_text:
                if question.multi_select:
                    if "__other__" not in selected_ids:
                        selected_ids.append("__other__")
                else:
                    selected_ids = ["__other__"]
            other_text = note_text if "__other__" in selected_ids and note_text else None
            selected_markdown = None
            if not question.multi_select:
                option_by_id = {option.id: option for option in question.options}
                for option_id in selected_ids:
                    option = option_by_id.get(option_id)
                    if option is not None and (option.markdown or "").strip():
                        selected_markdown = option.markdown
                        break

            annotation = None
            if selected_markdown:
                annotation = user_interaction.AskUserQuestionAnswer.Annotation(
                    markdown=selected_markdown,
                )

            answers.append(
                user_interaction.AskUserQuestionAnswer(
                    question_id=question.id,
                    selected_option_ids=selected_ids,
                    other_text=other_text,
                    note=note_text or None,
                    annotation=annotation,
                )
            )

        tui_display.show_progress_ui()
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(answers=answers),
        )

    # -- client wiring --

    def _on_session_info(info: SessionInfoSnapshot) -> None:
        if info.model_config_name:
            tui_display.set_model_name(info.model_config_name)
        if input_provider is not None:
            input_provider.set_pending_messages(info.follow_ups)

    def _report_herdr(event: events.Event) -> None:
        if herdr is None:
            return
        with contextlib.suppress(Exception):
            herdr.consume_event(event)
            if event.session_id != client.session_id:
                return
            if isinstance(event, events.TaskStartEvent):
                herdr.report_session_state(event.session_id, SessionRuntimeState.RUNNING)
            elif isinstance(event, events.TaskFinishEvent | events.InterruptEvent):
                herdr.report_session_state(event.session_id, SessionRuntimeState.IDLE)
            elif isinstance(event, events.UserInteractionRequestEvent):
                herdr.report_session_state(event.session_id, SessionRuntimeState.WAITING_USER_INPUT)
            elif isinstance(event, events.UserInteractionResolvedEvent):
                herdr.report_session_state(event.session_id, SessionRuntimeState.RUNNING)

    async def _on_envelope(envelope: events.EventEnvelope) -> None:
        _report_herdr(envelope.event)
        await tui_display.consume_envelope(envelope)

    client: RuntimeClient = SocketRuntimeClient(
        session_id,
        on_envelope=_on_envelope,
        on_session_info=_on_session_info,
        peek=peek,
    )

    def _agent_busy() -> bool:
        return client.is_running() or bool(local_turn_ops)

    def _session_work_dir() -> Path:
        raw = client.session_info().work_dir
        return Path(raw) if raw else Path.cwd()

    class _AwayRuntimeAdapter:
        def current_session_id(self) -> str | None:
            return client.session_id

        def has_running_tasks(self) -> bool:
            return _agent_busy()

        async def submit(self, operation: op.Operation) -> str:
            return await client.submit(operation)

    away_summary_coordinator = AwaySummaryCoordinator(runtime=_AwayRuntimeAdapter())
    loop = asyncio.get_running_loop()
    prompt_started = asyncio.Event()
    background_tasks: set[asyncio.Task[None]] = set()

    def _spawn(coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    # -- local display-control helpers --

    async def _toggle_transcript() -> None:
        await client.emit_local_event(events.ToggleTranscriptDetailEvent(session_id=client.session_id))
        await client.wait_for_display_idle()
        await settle_flicker_safe_stdout()

    def _request_toggle_transcript() -> None:
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(lambda: _spawn(_toggle_transcript()))

    async def _refresh_transcript() -> None:
        await client.emit_local_event(events.RefreshDisplayEvent(session_id=client.session_id))

    def _request_refresh_transcript() -> None:
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(lambda: _spawn(_refresh_transcript()))

    async def _change_model_from_prompt(model_name: str) -> None:
        await client.submit_and_wait(
            op.ChangeModelOperation(
                session_id=client.session_id,
                model_name=model_name,
                save_as_default=False,
                emit_welcome_event=True,
                emit_switch_message=False,
            )
        )

    async def _dequeue_remote() -> None:
        with contextlib.suppress(Exception):
            await client.dequeue_follow_ups()
        if input_provider is not None:
            input_provider.set_pending_messages(client.follow_up_texts())

    def _dequeue_pending_messages() -> tuple[str, ...]:
        texts = client.follow_up_texts()
        _spawn(_dequeue_remote())
        return texts

    def _on_prompt_start() -> None:
        prompt_started.set()
        tui_display.set_progress_ui_suspended(True)
        away_summary_coordinator.notify_prompt_started()

    def _on_prompt_end() -> None:
        away_summary_coordinator.notify_prompt_ended()
        if not _agent_busy():
            tui_display.set_progress_ui_suspended(False)

    def _pre_prompt() -> None:
        if not _agent_busy():
            tui_display.hide_progress_ui()

    input_provider = PromptToolkitInput(
        pre_prompt=_pre_prompt,
        on_prompt_start=_on_prompt_start,
        on_prompt_end=_on_prompt_end,
        on_user_activity=away_summary_coordinator.notify_user_activity,
        refresh_status=tui_display.refresh_prompt_status,
        get_current_model_config_name=lambda: client.session_info().model_config_name,
        get_current_model_provider_name=lambda: client.session_info().provider_name,
        get_current_model_effort=lambda: client.session_info().effort,
        on_change_model=_change_model_from_prompt,
        command_info_provider=get_command_info_list,
        request_toggle_transcript=_request_toggle_transcript,
        request_refresh_transcript=_request_refresh_transcript,
    )
    input_provider.set_dequeue_pending_messages(_dequeue_pending_messages)

    # -- interrupt handling (Esc / Ctrl+C while the agent runs) --

    interrupt_pending = False

    def _start_interrupt_once() -> None:
        nonlocal interrupt_pending
        if peek or interrupt_pending or not _agent_busy():
            return
        interrupt_pending = True
        _spawn(_submit_interrupt())

    async def _submit_interrupt() -> None:
        with contextlib.suppress(Exception):
            await client.submit(
                op.InterruptOperation(
                    session_id=client.session_id,
                    retract_unanswered_input=True,
                    # Esc mid-queue moves on to the next queued message
                    # (matches the pre-attach runner); kill keeps it stopped.
                    resume_follow_ups=True,
                )
            )

    def _request_interrupt_once() -> None:
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(_start_interrupt_once)

    # -- watcher: prompt busy state driven by client mirrors --

    async def _watch_state() -> None:
        nonlocal interrupt_pending
        ui_busy = False
        restore_sigint: Callable[[], None] | None = None
        state_changed = client.state_changed_event()
        while True:
            await state_changed.wait()
            state_changed.clear()
            input_provider.set_pending_messages(client.follow_up_texts())
            busy = _agent_busy()
            if busy and not ui_busy:
                ui_busy = True
                input_provider.set_agent_running(True)
                if not peek:
                    input_provider.set_interrupt_handler(_request_interrupt_once)
                    restore_sigint = install_sigint_interrupt(_request_interrupt_once)
                _start_prevent_sleep_if_needed()
                continue
            if not busy and ui_busy:
                # Debounce the idle gap between server-drained queue turns.
                if client.follow_up_texts() and not interrupt_pending:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(state_changed.wait(), timeout=1.0)
                    if _agent_busy():
                        continue
                ui_busy = False
                input_provider.set_interrupt_handler(None)
                if restore_sigint is not None:
                    with contextlib.suppress(Exception):
                        restore_sigint()
                    restore_sigint = None
                _stop_prevent_sleep_if_needed()
                await client.wait_for_display_idle()
                await settle_flicker_safe_stdout()
                away_summary_coordinator.notify_task_finished()
                prefill = client.consume_interrupt_prefill()
                if prefill is not None:
                    input_provider.set_next_prefill(prefill)
                interrupt_pending = False
                input_provider.set_pending_messages(client.follow_up_texts())
                input_provider.set_agent_running(False)

    # -- interaction consumer --

    async def _consume_interactions() -> None:
        queue = client.interaction_requests()
        while True:
            request_event = await queue.get()
            if peek:
                continue
            try:
                response = await _collect_interaction_response(request_event)
            except asyncio.CancelledError:
                raise
            except Exception:
                response = user_interaction.UserInteractionResponse(status="cancelled", payload=None)
            with contextlib.suppress(Exception):
                await client.submit(
                    op.UserInteractionRespondOperation(
                        session_id=request_event.session_id,
                        request_id=request_event.request_id,
                        response=response,
                    )
                )

    # -- startup: replay after the first prompt paint --

    async def _startup_replay() -> None:
        await prompt_started.wait()
        input_provider.set_startup_loading(True)
        try:
            client.start_display()
            try:
                await asyncio.wait_for(client.wait_for_replay_complete(), timeout=15.0)
            except TimeoutError:
                await _emit_local_notice(
                    "Attach replay did not complete — the server may be running older code. Try: klaude server reload"
                )
            await client.wait_for_display_idle()
            try:
                context_event = await asyncio.to_thread(
                    build_welcome_context_event,
                    session_id=client.session_id,
                    work_dir=_session_work_dir(),
                )
                await client.emit_local_event(context_event)
                await client.wait_for_display_idle()
            except Exception as exc:
                log_debug(f"Welcome context initialization failed: {exc}", debug_type=DebugType.EXECUTION)
        finally:
            input_provider.set_startup_loading(False)

    # -- submission helpers --

    async def _emit_local_notice(text: str) -> None:
        await client.emit_local_event(events.NoticeEvent(session_id=client.session_id, content=text))

    def _track_foreground_op(operation_id: str) -> None:
        local_turn_ops.add(operation_id)
        client.state_changed_event().set()

        async def _await_done() -> None:
            with contextlib.suppress(Exception):
                await client.wait_for(operation_id)
            local_turn_ops.discard(operation_id)
            client.state_changed_event().set()

        _spawn(_await_done())

    async def _submit_turn(run_op: op.RunAgentOperation) -> None:
        await client.submit(run_op)
        _track_foreground_op(run_op.id)

    def _queue_follow_ups(payloads: list[UserInputPayload]) -> None:
        # Optimistic: mirror + queue UI update now; the server confirm
        # (FollowUpQueueUpdatedEvent) reconciles. Awaiting the round trip in
        # the input loop kept the prompt — and the whole bottom bar — torn
        # down until the server replied: a visible blink on every queued
        # submission.
        client.optimistically_append_follow_ups([p.text for p in payloads])
        input_provider.set_pending_messages(client.follow_up_texts())

        async def _submit_queued() -> None:
            for payload in payloads:
                with contextlib.suppress(Exception):
                    await client.submit_and_wait(
                        op.FollowUpAgentOperation(session_id=client.session_id, input=payload)
                    )

        _spawn(_submit_queued())

    async def _reattach_to(new_session_id: str) -> None:
        await client.wait_for_display_idle()
        await client.reattach(new_session_id)
        client.start_display()
        await client.wait_for_replay_complete()

    async def _handle_command_result(result: CommandResult) -> None:
        for evt in result.events or []:
            await client.emit_local_event(evt)
        for operation in result.operations or []:
            if isinstance(operation, op.ClearSessionOperation):
                # /new: fresh server session in the same directory, same model.
                from klaude_code.tui.client.server_api import create_server_session

                new_id = await asyncio.to_thread(
                    create_server_session,
                    work_dir=_session_work_dir(),
                    model=client.session_info().model_config_name,
                )
                await _reattach_to(new_id)
                continue
            if isinstance(operation, op.ForkAndSwitchSessionOperation):
                await _reattach_to(operation.new_session_id)
                continue
            if isinstance(operation, op.RunAgentOperation):
                await _submit_turn(operation)
                continue
            await client.submit(operation)
            _track_foreground_op(operation.id)

    async def _dispatch_background_command(user_input: UserInputPayload) -> None:
        try:
            agent = await asyncio.to_thread(ClientCommandAgent, client.session_id, _session_work_dir())
            result = await dispatch_command(user_input, agent, submission_id=uuid4().hex)
        except Exception as exc:
            await _emit_local_notice(f"Command failed: {exc}")
            return
        for evt in result.events or []:
            await client.emit_local_event(evt)
        for operation in result.operations or []:
            await client.submit(operation)

    async def _submit_idle_input(user_input: UserInputPayload) -> None:
        """Dispatch one input while the session is idle."""
        text = user_input.text
        if text.startswith("！"):
            text = "!" + text[1:]
            user_input = UserInputPayload(text=text, images=user_input.images)

        await client.emit_user_message(
            events.UserMessageEvent(content=user_input.text, session_id=client.session_id, images=user_input.images)
        )

        if text.startswith("!"):
            command = text[1:].lstrip(" \t")
            if command == "":
                return
            bash_op = op.RunBashOperation(session_id=client.session_id, command=command)
            await client.submit(bash_op)
            _track_foreground_op(bash_op.id)
            return

        if text.lstrip().startswith("/"):
            run_in_foreground = has_interactive_command(text)
            try:
                agent = await asyncio.to_thread(ClientCommandAgent, client.session_id, _session_work_dir())
                result = await dispatch_command(user_input, agent, submission_id=uuid4().hex)
            except Exception as exc:
                await _emit_local_notice(f"Command failed: {exc}")
                return
            if run_in_foreground:
                # Interactive commands own the terminal; keep the prompt idle
                # and process their operations inline.
                for evt in result.events or []:
                    await client.emit_local_event(evt)
                for operation in result.operations or []:
                    await client.submit_and_wait(operation)
                await client.wait_for_display_idle()
                await settle_flicker_safe_stdout()
                return
            await _handle_command_result(result)
            await client.wait_for_display_idle()
            return

        await _submit_turn(op.RunAgentOperation(session_id=client.session_id, input=user_input))

    # -- main --

    watcher_task: asyncio.Task[None] | None = None
    interaction_task: asyncio.Task[None] | None = None
    startup_task: asyncio.Task[None] | None = None
    exited_via_ctrl_c = False

    try:
        await tui_display.start()
        await client.start()
        await away_summary_coordinator.start()

        watcher_task = asyncio.create_task(_watch_state())
        interaction_task = asyncio.create_task(_consume_interactions())
        startup_task = asyncio.create_task(_startup_replay())

        # Seed prompt state for mid-turn attaches.
        client.state_changed_event().set()

        await input_provider.start()
        inputs_iter = cast("AsyncGenerator[UserInputPayload]", input_provider.iter_inputs())
        async with contextlib.aclosing(inputs_iter) as inputs:
            async for user_input in inputs:
                if _is_exit_input(user_input.text):
                    break
                if user_input.text.strip() == "":
                    continue
                if peek:
                    await _emit_local_notice("Read-only attach (--peek): input is disabled.")
                    continue
                if has_background_command(user_input.text):
                    await _dispatch_background_command(user_input)
                    continue

                if interrupt_pending and _agent_busy():
                    # Esc-then-type: wait for the interrupted turn to wind
                    # down, then start a fresh turn with this input.
                    deadline = loop.time() + 10.0
                    state_changed = client.state_changed_event()
                    while _agent_busy() and loop.time() < deadline:
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(state_changed.wait(), timeout=0.25)
                        state_changed.clear()

                if _agent_busy():
                    if _is_command_shaped(user_input.text):
                        await _emit_local_notice(
                            "Commands cannot be queued while the agent is running; press Esc to interrupt first."
                        )
                        continue
                    _queue_follow_ups(list(_split_queue_edit_payload(user_input)))
                    continue

                payloads = _split_queue_edit_payload(user_input)
                first, rest = payloads[0], payloads[1:]
                await _submit_idle_input(first)
                if rest:
                    _queue_follow_ups(rest)

    except KeyboardInterrupt:
        exited_via_ctrl_c = True
    finally:
        tui_display.set_progress_ui_suspended(False)
        for task in (watcher_task, interaction_task, startup_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await task
        for task in list(background_tasks):
            if not task.done():
                task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)

        force_stop_prevent_sleep()
        with contextlib.suppress(Exception):
            await away_summary_coordinator.stop()

        was_running = client.is_running() or bool(client.follow_up_texts())
        if herdr is not None:
            with contextlib.suppress(Exception):
                await herdr.close()
        with contextlib.suppress(Exception):
            await client.close()
        with contextlib.suppress(Exception):
            await tui_display.stop()
        with contextlib.suppress(Exception):
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()

        # Detach semantics: the server keeps the session (and any running
        # task) alive; only this client goes away.
        work_dir = _session_work_dir()
        if exited_via_ctrl_c:
            log("Bye!")
        if Session.exists(client.session_id, work_dir=work_dir):
            short_id = Session.shortest_unique_prefix(client.session_id, work_dir=work_dir)
            if was_running:
                log(
                    ("detached, agent keeps running — reattach with:", "dim"),
                    (f"klaude attach {short_id}", "green"),
                )
            elif Session.has_user_messages(client.session_id, work_dir=work_dir):
                log(f"Session ID: {client.session_id}")
                log(f"Resume with: klaude -r {short_id}")
