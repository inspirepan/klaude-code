"""REPL keyboard bindings for prompt_toolkit.

This module provides the factory function to create key bindings for the REPL input,
with dependencies injected to avoid circular imports.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import cast

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Always, Filter
from prompt_toolkit.filters.app import has_completions
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent


def create_key_bindings(
    capture_clipboard_tag: Callable[[], str | None],
    copy_to_clipboard: Callable[[str], None],
    at_token_pattern: re.Pattern[str],
    *,
    input_enabled: Filter | None = None,
    open_model_picker: Callable[[], None] | None = None,
    open_thinking_picker: Callable[[], None] | None = None,
) -> KeyBindings:
    """Create REPL key bindings with injected dependencies.

    Args:
        capture_clipboard_tag: Callable to capture clipboard image and return tag
        copy_to_clipboard: Callable to copy text to system clipboard
        at_token_pattern: Pattern to match @token for completion refresh

    Returns:
        KeyBindings instance with all REPL handlers configured
    """
    kb = KeyBindings()
    enabled = input_enabled if input_enabled is not None else Always()

    def _should_submit_instead_of_accepting_completion(buf: Buffer) -> bool:
        """Return True when Enter should submit even if completions are visible.

        We show completions proactively for contexts like `/`.
        If the user already typed an exact candidate (e.g. `/clear`), accepting
        a completion often only adds a trailing space and makes Enter require
        two presses. In that case, prefer submitting.
        """
        state = buf.complete_state
        if state is None or not state.completions:
            return False

        try:
            doc = buf.document  # type: ignore[reportUnknownMemberType]
            text = cast(str, doc.text)  # type: ignore[reportUnknownMemberType]
            cursor_pos = cast(int, doc.cursor_position)  # type: ignore[reportUnknownMemberType]
        except Exception:
            return False

        # Only apply this heuristic when the caret is at the end of the buffer.
        if cursor_pos != len(text):
            return False

        for completion in state.completions:
            try:
                start = cursor_pos + completion.start_position
                if start < 0 or start > cursor_pos:
                    continue

                replaced = text[start:cursor_pos]
                inserted = completion.text

                # If the user already typed an exact candidate, don't force
                # accepting a completion (which often just adds a space).
                if replaced == inserted or replaced == inserted.rstrip():
                    return True
            except Exception:
                continue

        return False

    def _select_first_completion_if_needed(buf: Buffer) -> None:
        """Ensure the completion menu has an active selection.

        prompt_toolkit's default behavior keeps `complete_index=None` until the
        user explicitly selects an item. We want the first item to be selected
        by default, without modifying the buffer text.
        """
        state = buf.complete_state
        if state is None or not state.completions:
            return
        if state.complete_index is None:
            state.complete_index = 0

    def _cycle_completion(buf: Buffer, *, delta: int) -> None:
        state = buf.complete_state
        if state is None or not state.completions:
            return

        _select_first_completion_if_needed(buf)
        idx = state.complete_index or 0
        state.complete_index = (idx + delta) % len(state.completions)

    def _accept_current_completion(buf: Buffer) -> bool:
        """Apply the currently selected completion, if any.

        Returns True when a completion was applied.
        """
        state = buf.complete_state
        if state is None or not state.completions:
            return False

        _select_first_completion_if_needed(buf)
        completion = state.current_completion or state.completions[0]
        buf.apply_completion(completion)
        return True

    @kb.add("c-v", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Paste image from clipboard as [Image #N]."""
        tag = capture_clipboard_tag()
        if tag:
            with contextlib.suppress(Exception):
                event.current_buffer.insert_text(tag)  # pyright: ignore[reportUnknownMemberType]

    @kb.add("enter", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        buf = event.current_buffer
        doc = buf.document  # type: ignore

        # If VS Code/Windsurf/Cursor sent a "\\" sentinel before Enter (Shift+Enter mapping),
        # treat it as a request for a newline instead of submit.
        # This allows Shift+Enter to insert a newline in our multiline prompt.
        try:
            if doc.text_before_cursor.endswith("\\"):  # type: ignore[reportUnknownMemberType]
                buf.delete_before_cursor()  # remove the sentinel backslash  # type: ignore[reportUnknownMemberType]
                buf.insert_text("\n")  # type: ignore[reportUnknownMemberType]
                return
        except (AttributeError, TypeError):
            # Fall through to default behavior if anything goes wrong
            pass

        # When completions are visible, Enter accepts the current selection.
        # This aligns with common TUI completion UX: navigation doesn't modify
        # the buffer, and Enter/Tab inserts the selected option.
        if not _should_submit_instead_of_accepting_completion(buf) and _accept_current_completion(buf):
            return

        # If the entire buffer is whitespace-only, insert a newline rather than submitting.
        if len(buf.text.strip()) == 0:  # type: ignore
            buf.insert_text("\n")  # type: ignore
            return

        # No need to persist manifest anymore - iter_inputs will handle image extraction
        buf.validate_and_handle()  # type: ignore

    @kb.add("tab", filter=enabled & has_completions)
    def _(event: KeyPressEvent) -> None:
        buf = event.current_buffer
        if _accept_current_completion(buf):
            event.app.invalidate()  # type: ignore[reportUnknownMemberType]

    @kb.add("down", filter=enabled & has_completions)
    def _(event: KeyPressEvent) -> None:
        buf = event.current_buffer
        _cycle_completion(buf, delta=1)
        event.app.invalidate()  # type: ignore[reportUnknownMemberType]

    @kb.add("up", filter=enabled & has_completions)
    def _(event: KeyPressEvent) -> None:
        buf = event.current_buffer
        _cycle_completion(buf, delta=-1)
        event.app.invalidate()  # type: ignore[reportUnknownMemberType]

    @kb.add("c-j", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")  # type: ignore

    @kb.add("c", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Copy selected text to system clipboard, or insert 'c' if no selection."""
        buf = event.current_buffer  # type: ignore
        if buf.selection_state:  # type: ignore[reportUnknownMemberType]
            doc = buf.document  # type: ignore[reportUnknownMemberType]
            start, end = doc.selection_range()  # type: ignore[reportUnknownMemberType]
            selected_text: str = doc.text[start:end]  # type: ignore[reportUnknownMemberType]

            if selected_text:
                copy_to_clipboard(selected_text)  # type: ignore[reportUnknownArgumentType]
            buf.exit_selection()  # type: ignore[reportUnknownMemberType]
        else:
            buf.insert_text("c")  # type: ignore[reportUnknownMemberType]

    @kb.add("backspace", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Ensure completions refresh on backspace when editing an @token.

        We delete the character before cursor (default behavior), then explicitly
        trigger completion refresh if the caret is still within an @... token.
        """
        buf = event.current_buffer  # type: ignore
        # Handle selection: cut selection if present, otherwise delete one character
        if buf.selection_state:  # type: ignore[reportUnknownMemberType]
            buf.cut_selection()  # type: ignore[reportUnknownMemberType]
        else:
            buf.delete_before_cursor()  # type: ignore[reportUnknownMemberType]
        # If the token pattern still applies, refresh completion popup
        try:
            text_before = buf.document.text_before_cursor  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]
            # Check for both @ tokens and / tokens (slash commands on first line only)
            should_refresh = False
            if at_token_pattern.search(text_before):  # type: ignore[reportUnknownArgumentType]
                should_refresh = True
            elif buf.document.cursor_position_row == 0:  # type: ignore[reportUnknownMemberType]
                # Check for slash command pattern without accessing protected attribute
                text_before_str = text_before or ""
                if text_before_str.strip().startswith("/") and " " not in text_before_str:
                    should_refresh = True

            if should_refresh:
                buf.start_completion(select_first=False)  # type: ignore[reportUnknownMemberType]
        except (AttributeError, TypeError):
            pass

    @kb.add("left", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Support wrapping to previous line when pressing left at column 0."""
        buf = event.current_buffer  # type: ignore
        try:
            doc = buf.document  # type: ignore[reportUnknownMemberType]
            row = cast(int, doc.cursor_position_row)  # type: ignore[reportUnknownMemberType]
            col = cast(int, doc.cursor_position_col)  # type: ignore[reportUnknownMemberType]

            # At the beginning of a non-first line: jump to previous line end.
            if col == 0 and row > 0:
                lines = cast(list[str], doc.lines)  # type: ignore[reportUnknownMemberType]
                prev_row = row - 1
                if 0 <= prev_row < len(lines):
                    prev_line = lines[prev_row]
                    new_index = doc.translate_row_col_to_index(prev_row, len(prev_line))  # type: ignore[reportUnknownMemberType]
                    buf.cursor_position = new_index  # type: ignore[reportUnknownMemberType]
                return

            # Default behavior: move one character left when possible.
            if doc.cursor_position > 0:  # type: ignore[reportUnknownMemberType]
                buf.cursor_left()  # type: ignore[reportUnknownMemberType]
        except (AttributeError, IndexError, TypeError):
            pass

    @kb.add("right", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Support wrapping to next line when pressing right at line end."""
        buf = event.current_buffer  # type: ignore
        try:
            doc = buf.document  # type: ignore[reportUnknownMemberType]
            row = cast(int, doc.cursor_position_row)  # type: ignore[reportUnknownMemberType]
            col = cast(int, doc.cursor_position_col)  # type: ignore[reportUnknownMemberType]
            lines = cast(list[str], doc.lines)  # type: ignore[reportUnknownMemberType]

            current_line = lines[row] if 0 <= row < len(lines) else ""
            at_line_end = col >= len(current_line)
            is_last_line = row >= len(lines) - 1 if lines else True

            # At end of a non-last line: jump to next line start.
            if at_line_end and not is_last_line:
                next_row = row + 1
                new_index = doc.translate_row_col_to_index(next_row, 0)  # type: ignore[reportUnknownMemberType]
                buf.cursor_position = new_index  # type: ignore[reportUnknownMemberType]
                return

            # Default behavior: move one character right when possible.
            if doc.cursor_position < len(doc.text):  # type: ignore[reportUnknownMemberType]
                buf.cursor_right()  # type: ignore[reportUnknownMemberType]
        except (AttributeError, IndexError, TypeError):
            pass

    @kb.add("c-l", filter=enabled, eager=True)
    def _(event: KeyPressEvent) -> None:
        del event
        if open_model_picker is not None:
            with contextlib.suppress(Exception):
                open_model_picker()

    @kb.add("c-t", filter=enabled, eager=True)
    def _(event: KeyPressEvent) -> None:
        del event
        if open_thinking_picker is not None:
            with contextlib.suppress(Exception):
                open_thinking_picker()

    return kb
