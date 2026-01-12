from __future__ import annotations

import asyncio
import contextlib
import sys
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
from klaude_code.const import SIGINT_DOUBLE_PRESS_EXIT_TEXT
from klaude_code.core.compaction import should_compact_threshold
from klaude_code.core.executor import Executor
from klaude_code.log import get_current_log_file, log
from klaude_code.protocol import events, llm_param, op
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
from klaude_code.tui.terminal.control import install_sigint_double_press_exit, start_esc_interrupt_monitor
from klaude_code.ui.terminal.title import update_terminal_title
from klaude_code.update import get_update_message


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

    display: ui.DisplayABC = TUIDisplay(theme=theme)
    if init_config.debug:
        display = ui.DebugEventDisplay(display)

    components = await initialize_app_components(
        init_config=init_config,
        display=display,
        on_model_change=update_terminal_title,
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
        elif (
            isinstance(active_display, ui.DebugEventDisplay)
            and active_display.wrapped_display
            and isinstance(active_display.wrapped_display, TUIDisplay)
        ):
            active_display.wrapped_display.hide_progress_ui()

    is_light_background: bool | None = None
    if theme == "light":
        is_light_background = True
    elif theme == "dark":
        is_light_background = False

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
        is_light_background=is_light_background,
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
        if (
            isinstance(active_display, ui.DebugEventDisplay)
            and active_display.wrapped_display
            and isinstance(active_display.wrapped_display, TUIDisplay)
        ):
            return active_display.wrapped_display
        return None

    @contextlib.contextmanager
    def _double_ctrl_c_to_exit_while_running(*, window_seconds: float = 2.0):
        """Require double Ctrl+C to exit while waiting for task completion."""

        def _show_toast_once() -> None:
            def _emit() -> None:
                tui_display = _get_tui_display()
                if tui_display is not None:
                    with contextlib.suppress(Exception):
                        tui_display.show_sigint_exit_toast(window_seconds=window_seconds)
                    return
                print(SIGINT_DOUBLE_PRESS_EXIT_TEXT, file=sys.stderr)

            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(_emit)
                return
            _emit()

        def _hide_progress() -> None:
            def _emit() -> None:
                tui_display = _get_tui_display()
                if tui_display is None:
                    return
                with contextlib.suppress(Exception):
                    tui_display.hide_progress_ui()

            with contextlib.suppress(Exception):
                loop.call_soon_threadsafe(_emit)

        restore_sigint = install_sigint_double_press_exit(
            _show_toast_once,
            _hide_progress,
            window_seconds=window_seconds,
        )
        try:
            yield
        finally:
            with contextlib.suppress(Exception):
                restore_sigint()

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
                with _double_ctrl_c_to_exit_while_running():
                    await components.executor.wait_for(wait_id)
                # Ensure all trailing events (e.g. final deltas / spinner stop) are rendered
                # before handing control back to prompt_toolkit.
                await components.event_queue.join()
                continue

            async def _on_esc_interrupt() -> None:
                await components.executor.submit(op.InterruptOperation(target_session_id=_get_active_session_id()))

            stop_event, esc_task = start_esc_interrupt_monitor(_on_esc_interrupt)
            try:
                with _double_ctrl_c_to_exit_while_running():
                    await components.executor.wait_for(wait_id)
                # Ensure all trailing events (e.g. final deltas / spinner stop) are rendered
                # before handing control back to prompt_toolkit.
                await components.event_queue.join()
            finally:
                stop_event.set()
                with contextlib.suppress(Exception):
                    await esc_task

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
