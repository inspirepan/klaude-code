from __future__ import annotations

import asyncio
import contextlib
import shutil
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from klaude_code.app.ports import DisplayABC, InputProviderABC, InteractionHandlerABC
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
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.log import get_current_log_file, log
from klaude_code.protocol import events, llm_param, op, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session.session import Session
from klaude_code.tui.command import (
    dispatch_command,
    get_command_info_list,
)
from klaude_code.tui.command.command_abc import WebModeRequest
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input import build_repl_status_snapshot
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput, REPLStatusSnapshot
from klaude_code.tui.terminal.color import is_light_terminal_background
from klaude_code.tui.terminal.control import install_sigint_interrupt, start_esc_interrupt_monitor
from klaude_code.tui.terminal.selector import (
    DEFAULT_PICKER_STYLE,
    QuestionPrompt,
    SelectItem,
    build_model_select_items,
    select_one,
    select_questions,
)
from klaude_code.tui.terminal.title import update_terminal_title
from klaude_code.update import get_update_message


async def submit_user_input_payload(
    *,
    runtime: RuntimeFacade,
    wait_for_display_idle: Callable[[], Awaitable[None]],
    user_input: UserInputPayload,
    session_id: str | None,
) -> SubmitUserInputResult:
    """Parse/dispatch a user input payload (TUI commands) and submit operations.

    This function is TUI-only: it supports slash command parsing and interactive prompts.

    Returns the submitted operation id to await, plus any requested mode transition.
    """

    sid = session_id or runtime.current_session_id()
    if sid is None:
        raise RuntimeError("No active session")

    agent = runtime.current_agent
    if agent is None or agent.session.id != sid:
        await runtime.submit_and_wait(op.InitAgentOperation(session_id=sid, work_dir=Path.cwd()))
        agent = runtime.current_agent

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
    await runtime.emit_event(events.UserMessageEvent(content=user_input.text, session_id=sid, images=user_input.images))

    # Bash mode: run a user-entered command without invoking the agent.
    if user_input.text.startswith("!"):
        command = user_input.text[1:].lstrip(" \t")
        if command == "":
            # Enter should be ignored in the input layer for this case; keep a guard here.
            return SubmitUserInputResult(wait_id=None)
        bash_op = op.RunBashOperation(id=submission_id, session_id=sid, command=command)
        return SubmitUserInputResult(wait_id=await runtime.submit(bash_op))

    cmd_result = await dispatch_command(user_input, agent, submission_id=submission_id)
    operations: list[op.Operation] = list(cmd_result.operations or [])
    if cmd_result.web_mode_request is not None and operations:
        raise ValueError("Web mode transition cannot be combined with operations")

    run_ops = [candidate for candidate in operations if isinstance(candidate, op.RunAgentOperation)]
    if len(run_ops) > 1:
        raise ValueError("Multiple RunAgentOperation results are not supported")

    if cmd_result.events:
        for evt in cmd_result.events:
            await runtime.emit_event(evt)

    if run_ops and should_compact_threshold(
        session=agent.session,
        config=None,
        llm_config=agent.profile.llm_client.get_llm_config(),
    ):
        await runtime.submit_and_wait(
            op.CompactSessionOperation(
                session_id=agent.session.id,
                reason="threshold",
                will_retry=False,
            )
        )

    submitted_ids: list[str] = []
    for operation_item in operations:
        submitted_ids.append(await runtime.submit(operation_item))

    if not submitted_ids:
        # Ensure event-only commands are fully rendered before showing the next prompt.
        await wait_for_display_idle()
        return SubmitUserInputResult(wait_id=None, web_mode_request=cmd_result.web_mode_request)

    if run_ops:
        return SubmitUserInputResult(wait_id=run_ops[0].id)
    return SubmitUserInputResult(wait_id=submitted_ids[-1])


@dataclass(frozen=True, slots=True)
class SubmitUserInputResult:
    wait_id: str | None
    web_mode_request: WebModeRequest | None = None


async def run_interactive(init_config: AppInitConfig, session_id: str | None = None) -> WebModeRequest | None:
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
    display: DisplayABC = tui_display
    pause_esc_monitor: Callable[[], Awaitable[None]] | None = None
    resume_esc_monitor: Callable[[], None] | None = None

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

        # Fetch model entries and keep only those present in the payload
        config = load_config()
        entries = [
            m for m in config.iter_model_entries(only_available=True, include_disabled=False) if m.selector in valid_ids
        ]
        model_selectors = {m.selector for m in entries}

        # Build items using the shared builder (identical to --model CLI)
        items = build_model_select_items(entries)

        # Prepend any non-model options (e.g., "__default__" for sub-agent config)
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
            style=DEFAULT_PICKER_STYLE,
        )
        return selected if isinstance(selected, str) else None

    def _pick_option_with_selector_style(payload: user_interaction.OperationSelectRequestPayload) -> str | None:
        selected = select_one(
            message=payload.question,
            items=_build_operation_select_items(payload),
            pointer="→",
            use_search_filter=True,
            style=DEFAULT_PICKER_STYLE,
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

    async def _collect_interaction_response(
        request_event: events.UserInteractionRequestEvent,
    ) -> user_interaction.UserInteractionResponse:
        payload = request_event.payload
        if payload.kind == "operation_select":
            tui_display.hide_progress_ui()
            if pause_esc_monitor is not None:
                await pause_esc_monitor()

            try:
                if request_event.source == "operation_model":
                    selected = await asyncio.to_thread(_pick_model_with_model_picker_style, payload)
                else:
                    selected = await asyncio.to_thread(_pick_option_with_selector_style, payload)
            finally:
                if resume_esc_monitor is not None:
                    resume_esc_monitor()

            if selected is None:
                return user_interaction.UserInteractionResponse(status="cancelled", payload=None)
            tui_display.show_progress_ui()
            return _submitted_single_choice_response(selected_option_id=selected)

        if payload.kind != "ask_user_question":
            return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        answers: list[user_interaction.AskUserQuestionAnswer] = []
        if request_event.source == "tool":
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

        if pause_esc_monitor is not None:
            await pause_esc_monitor()

        try:
            selections = await asyncio.to_thread(
                select_questions,
                questions=prompts,
                pointer="→",
                style=DEFAULT_PICKER_STYLE,
            )
        finally:
            if resume_esc_monitor is not None:
                resume_esc_monitor()

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

            answers.append(
                user_interaction.AskUserQuestionAnswer(
                    question_id=question.id,
                    selected_option_ids=selected_ids,
                    other_text=other_text,
                    note=note_text or None,
                )
            )

        tui_display.show_progress_ui()
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(answers=answers),
        )

    class _TUIInteractionHandler(InteractionHandlerABC):
        async def collect_response(
            self,
            request_event: events.UserInteractionRequestEvent,
        ) -> user_interaction.UserInteractionResponse:
            return await _collect_interaction_response(request_event)

    def _on_model_change(model_name: str) -> None:
        tui_display.set_model_name(model_name)

    components = await initialize_app_components(
        init_config=init_config,
        display=display,
        interaction_handler=_TUIInteractionHandler(),
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

        This is necessary because /new creates a new session with a different id.
        """

        return components.runtime.current_session_id()

    async def _change_model_from_prompt(model_name: str) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.runtime.submit_and_wait(
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
        agent = components.runtime.current_agent
        if agent is None:
            return None
        return agent.profile.llm_client.get_llm_config()

    async def _change_thinking_from_prompt(thinking: llm_param.Thinking) -> None:
        sid = _get_active_session_id()
        if not sid:
            return
        await components.runtime.submit_and_wait(
            op.ChangeThinkingOperation(
                session_id=sid,
                thinking=thinking,
                emit_welcome_event=True,
                emit_switch_message=False,
            )
        )

    input_provider: InputProviderABC = PromptToolkitInput(
        status_provider=_status_provider,
        pre_prompt=_stop_rich_bottom_ui,
        get_current_model_config_name=lambda: (
            components.runtime.current_agent.session.model_config_name
            if components.runtime.current_agent is not None
            else None
        ),
        on_change_model=_change_model_from_prompt,
        get_current_llm_config=_get_current_llm_config,
        on_change_thinking=_change_thinking_from_prompt,
        command_info_provider=get_command_info_list,
    )

    loop = asyncio.get_running_loop()

    async def _wait_for_with_interrupt(wait_id: str, *, session_id: str) -> None:
        nonlocal pause_esc_monitor, resume_esc_monitor
        wait_task = asyncio.create_task(components.runtime.wait_for(wait_id))
        interrupt_requested = False
        interrupt_task: asyncio.Task[None] | None = None
        esc_monitor: tuple[threading.Event, asyncio.Task[None]] | None = None

        async def _submit_interrupt(target_session_id: str) -> None:
            await components.runtime.submit_and_wait(op.InterruptOperation(session_id=target_session_id))

        async def _on_esc_interrupt() -> None:
            _request_interrupt_once()

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

        def _start_interrupt_once() -> None:
            nonlocal interrupt_requested, interrupt_task
            if interrupt_requested:
                return
            interrupt_requested = True
            interrupt_task = asyncio.create_task(_submit_interrupt(session_id))

        def _request_interrupt_once() -> None:
            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(_start_interrupt_once)

        pause_esc_monitor = _stop_esc_monitor
        resume_esc_monitor = _start_esc_monitor
        _start_esc_monitor()
        restore_sigint = install_sigint_interrupt(_request_interrupt_once)

        try:
            await wait_task
        finally:
            pause_esc_monitor = None
            resume_esc_monitor = None
            await _stop_esc_monitor()
            with contextlib.suppress(Exception):
                restore_sigint()
            if interrupt_task is not None and not interrupt_task.done():
                with contextlib.suppress(Exception):
                    await interrupt_task
            if not wait_task.done():
                wait_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await wait_task

    exit_hint_printed = False
    pending_web_mode_request: WebModeRequest | None = None

    try:
        tui_holder_key = uuid4().hex
        await initialize_session(
            components.runtime,
            components.wait_for_display_idle,
            session_id=session_id,
            holder_key=tui_holder_key,
        )
        backfill_session_model_config(
            components.runtime.current_agent,
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
            submission = await submit_user_input_payload(
                runtime=components.runtime,
                wait_for_display_idle=components.wait_for_display_idle,
                user_input=user_input,
                session_id=active_session_id,
            )

            wait_id = submission.wait_id
            if submission.web_mode_request is not None:
                pending_web_mode_request = submission.web_mode_request
                break

            if wait_id is None:
                continue

            if active_session_id is None:
                continue

            await _wait_for_with_interrupt(wait_id, session_id=active_session_id)
            # Ensure all trailing events (e.g. final deltas / spinner stop) are rendered
            # before handing control back to prompt_toolkit.
            await components.wait_for_display_idle()

    except KeyboardInterrupt:
        await handle_keyboard_interrupt(components.runtime)
        exit_hint_printed = True
    finally:
        active_session_id = components.runtime.current_session_id()
        work_dir = Path.cwd()
        await cleanup_app_components(components)

        if active_session_id and Session.exists(active_session_id, work_dir=work_dir):
            with contextlib.suppress(Exception):
                session = Session.load(active_session_id, work_dir=work_dir)
                if session.messages_count == 0:
                    shutil.rmtree(Session.paths(work_dir).session_dir(active_session_id), ignore_errors=True)

        if (
            pending_web_mode_request is None
            and not exit_hint_printed
            and active_session_id
            and Session.exists(active_session_id, work_dir=work_dir)
        ):
            short_id = Session.shortest_unique_prefix(active_session_id, work_dir=work_dir)
            log(f"Session ID: {active_session_id}")
            log(f"Resume with: klaude -r {short_id}")

    return pending_web_mode_request
