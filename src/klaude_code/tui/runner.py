from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import TYPE_CHECKING
from uuid import uuid4

from klaude_code import ui
from klaude_code.app.runtime import (
    AppInitConfig,
    backfill_session_model_config,
    cleanup_app_components,
    handle_keyboard_interrupt,
    initialize_app_components,
    initialize_session,
)
from klaude_code.config import load_config
from klaude_code.core.compaction import should_compact_threshold
from klaude_code.core.executor import Executor
from klaude_code.log import get_current_log_file, log
from klaude_code.protocol import events, llm_param, op, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session.session import Session
from klaude_code.tui.command import (
    dispatch_command,
    get_command_info_list,
    has_interactive_command,
)
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input import build_repl_status_snapshot
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput, REPLStatusSnapshot
from klaude_code.tui.terminal.color import is_light_terminal_background
from klaude_code.tui.terminal.control import install_sigint_interrupt, start_esc_interrupt_monitor
from klaude_code.tui.terminal.selector import (
    DEFAULT_PICKER_STYLE,
    QuestionPrompt,
    SelectItem,
    select_questions,
)
from klaude_code.ui.terminal.title import update_terminal_title
from klaude_code.update import get_update_message

if TYPE_CHECKING:
    from klaude_code.core.user_interaction import PendingUserInteractionRequest


async def submit_user_input_payload(
    *,
    executor: Executor,
    event_queue: asyncio.Queue[events.Event],
    user_input: UserInputPayload,
    session_id: str | None,
) -> str | None:
    """Parse/dispatch a user input payload (TUI commands) and submit operations.

    This function is TUI-only: it supports slash command parsing and interactive prompts.

    Returns a submission id that should be awaited, or None if there is nothing
    to wait for (e.g. commands that only emit events).
    """

    sid = session_id or executor.context.current_session_id()
    if sid is None:
        raise RuntimeError("No active session")

    agent = executor.context.current_agent
    if agent is None or agent.session.id != sid:
        await executor.submit_and_wait(op.InitAgentOperation(session_id=sid))
        agent = executor.context.current_agent

    if agent is None:
        raise RuntimeError("Failed to initialize agent")

    submission_id = uuid4().hex

    # Normalize a leading full-width exclamation mark for consistent UI/history.
    # (Bash mode is triggered only when the first character is `!`.)
    text = user_input.text
    if text.startswith("！"):
        text = "!" + text[1:]
        user_input = UserInputPayload(text=text, images=user_input.images)

    # Render the raw user input in the TUI even when it resolves to an event-only command.
    await executor.context.emit_event(
        events.UserMessageEvent(content=user_input.text, session_id=sid, images=user_input.images)
    )

    # Bash mode: run a user-entered command without invoking the agent.
    if user_input.text.startswith("!"):
        command = user_input.text[1:].lstrip(" \t")
        if command == "":
            # Enter should be ignored in the input layer for this case; keep a guard here.
            return None
        bash_op = op.RunBashOperation(id=submission_id, session_id=sid, command=command)
        return await executor.submit(bash_op)

    cmd_result = await dispatch_command(user_input, agent, submission_id=submission_id)
    operations: list[op.Operation] = list(cmd_result.operations or [])

    run_ops = [candidate for candidate in operations if isinstance(candidate, op.RunAgentOperation)]
    if len(run_ops) > 1:
        raise ValueError("Multiple RunAgentOperation results are not supported")

    if cmd_result.events:
        for evt in cmd_result.events:
            await executor.context.emit_event(evt)

    if run_ops and should_compact_threshold(
        session=agent.session,
        config=None,
        llm_config=agent.profile.llm_client.get_llm_config(),
    ):
        await executor.submit_and_wait(
            op.CompactSessionOperation(
                session_id=agent.session.id,
                reason="threshold",
                will_retry=False,
            )
        )

    submitted_ids: list[str] = []
    for operation_item in operations:
        submitted_ids.append(await executor.submit(operation_item))

    if not submitted_ids:
        # Ensure event-only commands are fully rendered before showing the next prompt.
        await event_queue.join()
        return None

    if run_ops:
        return run_ops[0].id
    return submitted_ids[-1]


async def run_interactive(init_config: AppInitConfig, session_id: str | None = None) -> None:
    """Run the interactive REPL (TUI).

    If session_id is None, a new session is created.
    If session_id is provided, attempts to resume that session.
    """

    update_terminal_title()

    cfg = load_config()
    theme: str | None = cfg.theme
    if theme is None:
        detected = is_light_terminal_background()
        if detected is True:
            theme = "light"
        elif detected is False:
            theme = "dark"

    tui_display = TUIDisplay(theme=theme)
    display: ui.DisplayABC = tui_display

    def _on_model_change(model_name: str) -> None:
        update_terminal_title(model_name)
        tui_display.set_model_name(model_name)

    components = await initialize_app_components(
        init_config=init_config,
        display=display,
        on_model_change=_on_model_change,
    )

    def _status_provider() -> REPLStatusSnapshot:
        update_message = get_update_message()
        debug_log = get_current_log_file()
        debug_log_path = str(debug_log) if debug_log else None
        return build_repl_status_snapshot(update_message, debug_log_path=debug_log_path)

    def _stop_rich_bottom_ui() -> None:
        active_display = components.display
        if isinstance(active_display, TUIDisplay):
            active_display.hide_progress_ui()

    def _get_active_session_id() -> str | None:
        """Get the current active session ID dynamically.

        This is necessary because /clear creates a new session with a different id.
        """

        return components.executor.context.current_session_id()

    async def _change_model_from_prompt(model_name: str) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.executor.submit_and_wait(
            op.ChangeModelOperation(
                session_id=sid,
                model_name=model_name,
                save_as_default=False,
                defer_thinking_selection=True,
                emit_welcome_event=True,
                emit_switch_message=False,
            )
        )

    def _get_current_llm_config() -> llm_param.LLMConfigParameter | None:
        agent = components.executor.context.current_agent
        if agent is None:
            return None
        return agent.profile.llm_client.get_llm_config()

    async def _change_thinking_from_prompt(thinking: llm_param.Thinking) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.executor.submit_and_wait(
            op.ChangeThinkingOperation(
                session_id=sid,
                thinking=thinking,
                emit_welcome_event=True,
                emit_switch_message=False,
            )
        )

    input_provider: ui.InputProviderABC = PromptToolkitInput(
        status_provider=_status_provider,
        pre_prompt=_stop_rich_bottom_ui,
        get_current_model_config_name=lambda: (
            components.executor.context.current_agent.session.model_config_name
            if components.executor.context.current_agent is not None
            else None
        ),
        on_change_model=_change_model_from_prompt,
        get_current_llm_config=_get_current_llm_config,
        on_change_thinking=_change_thinking_from_prompt,
        command_info_provider=get_command_info_list,
    )

    loop = asyncio.get_running_loop()

    def _get_tui_display() -> TUIDisplay | None:
        active_display = components.display
        if isinstance(active_display, TUIDisplay):
            return active_display
        return None

    def _build_question_items(
        question: user_interaction.AskUserQuestionQuestion,
    ) -> list[SelectItem[str]]:
        items: list[SelectItem[str]] = []
        for idx, option in enumerate(question.options, start=1):
            title: list[tuple[str, str]] = [
                ("class:msg", f"{idx}. {option.label}\n"),
                ("class:meta", f"    {option.description}\n"),
            ]
            items.append(
                SelectItem(
                    title=title,
                    value=option.id,
                    search_text=f"{option.label} {option.description}",
                    summary=option.label,
                )
            )
        return items

    async def _collect_interaction_response(
        request: PendingUserInteractionRequest,
    ) -> user_interaction.UserInteractionResponse:
        payload = request.payload
        if payload.kind != "ask_user_question":
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        answers: list[user_interaction.AskUserQuestionAnswer] = []
        tui_display = _get_tui_display()
        if tui_display is not None:
            tui_display.notify_ask_user_question(question_count=len(payload.questions))
            tui_display.hide_progress_ui()

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

        selections = await asyncio.to_thread(
            select_questions,
            questions=prompts,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
        )
        if selections is None:
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        for question, selection in zip(payload.questions, selections, strict=False):
            option_label_by_id = {option.id: option.label for option in question.options}
            selected_ids = list(selection.selected_values)
            selected_labels: list[str] = []
            for selected in selected_ids:
                if selected == "__other__":
                    selected_labels.append("Other")
                else:
                    selected_labels.append(option_label_by_id.get(selected, selected))

            note_text = selection.input_text.strip()
            other_text = note_text if "__other__" in selected_ids and note_text else None

            answers.append(
                user_interaction.AskUserQuestionAnswer(
                    question_id=question.id,
                    selected_option_ids=selected_ids,
                    selected_option_labels=selected_labels,
                    other_text=other_text,
                    note=note_text or None,
                )
            )

        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(answers=answers),
        )

    async def _wait_for_with_interactions(wait_id: str) -> None:
        wait_task = asyncio.create_task(components.executor.wait_for(wait_id))
        manager = components.executor.context.user_interaction_manager
        interrupt_requested = False
        interrupt_task: asyncio.Task[None] | None = None

        async def _submit_interrupt(target_session_id: str | None) -> None:
            await components.executor.submit_and_wait(op.InterruptOperation(target_session_id=target_session_id))

        def _start_interrupt_once() -> None:
            nonlocal interrupt_requested, interrupt_task
            if interrupt_requested:
                return
            interrupt_requested = True
            interrupt_task = asyncio.create_task(_submit_interrupt(_get_active_session_id()))

        def _request_interrupt_once() -> None:
            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(_start_interrupt_once)

        async def _on_esc_interrupt() -> None:
            _request_interrupt_once()

        esc_monitor: tuple[threading.Event, asyncio.Task[None]] | None = None

        def _start_esc_monitor() -> None:
            nonlocal esc_monitor
            if esc_monitor is not None:
                return
            esc_monitor = start_esc_interrupt_monitor(_on_esc_interrupt)

        async def _stop_esc_monitor() -> None:
            nonlocal esc_monitor
            if esc_monitor is None:
                return
            stop_event, esc_task = esc_monitor
            esc_monitor = None
            stop_event.set()
            with contextlib.suppress(Exception):
                await esc_task

        _start_esc_monitor()
        restore_sigint = install_sigint_interrupt(_request_interrupt_once)

        try:
            while True:
                request_task = asyncio.create_task(manager.wait_next_request())
                done, _ = await asyncio.wait({wait_task, request_task}, return_when=asyncio.FIRST_COMPLETED)
                if wait_task in done:
                    request_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await request_task
                    break

                request = request_task.result()
                await _stop_esc_monitor()
                response = await _collect_interaction_response(request)
                if response.status == "submitted":
                    tui_display = _get_tui_display()
                    if tui_display is not None:
                        tui_display.show_progress_ui()
                await components.executor.submit_and_wait(
                    op.UserInteractionRespondOperation(
                        session_id=request.session_id,
                        request_id=request.request_id,
                        response=response,
                    )
                )
                if not wait_task.done():
                    _start_esc_monitor()
        finally:
            with contextlib.suppress(Exception):
                restore_sigint()
            if interrupt_task is not None and not interrupt_task.done():
                with contextlib.suppress(Exception):
                    await interrupt_task
            await _stop_esc_monitor()
            if not wait_task.done():
                wait_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await wait_task

    exit_hint_printed = False

    try:
        await initialize_session(components.executor, components.event_queue, session_id=session_id)
        backfill_session_model_config(
            components.executor.context.current_agent,
            init_config.model,
            components.config.main_model,
            is_new_session=session_id is None,
        )

        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            if user_input.text.strip().lower() in {"exit", ":q", "quit"}:
                break
            if user_input.text.strip() == "":
                continue

            active_session_id = _get_active_session_id()
            is_interactive = has_interactive_command(user_input.text)

            wait_id = await submit_user_input_payload(
                executor=components.executor,
                event_queue=components.event_queue,
                user_input=user_input,
                session_id=active_session_id,
            )

            if wait_id is None:
                continue

            if is_interactive:
                await _wait_for_with_interactions(wait_id)
                # Ensure all trailing events (e.g. final deltas / spinner stop) are rendered
                # before handing control back to prompt_toolkit.
                await components.event_queue.join()
                continue

            await _wait_for_with_interactions(wait_id)
            # Ensure all trailing events (e.g. final deltas / spinner stop) are rendered
            # before handing control back to prompt_toolkit.
            await components.event_queue.join()

    except KeyboardInterrupt:
        await handle_keyboard_interrupt(components.executor)
        exit_hint_printed = True
    finally:
        await cleanup_app_components(components)

        if not exit_hint_printed:
            active_session_id = components.executor.context.current_session_id()
            if active_session_id and Session.exists(active_session_id):
                short_id = Session.shortest_unique_prefix(active_session_id)
                log(f"Session ID: {active_session_id}")
                log(f"Resume with: klaude -r {short_id}")
