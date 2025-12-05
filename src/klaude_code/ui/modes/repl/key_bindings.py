"""REPL keyboard bindings for prompt_toolkit.

This module provides the factory function to create key bindings for the REPL input,
with dependencies injected to avoid circular imports.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import cast

from prompt_toolkit.key_binding import KeyBindings


def create_key_bindings(
    capture_clipboard_tag: Callable[[], str | None],
    copy_to_clipboard: Callable[[str], None],
    at_token_pattern: re.Pattern[str],
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

    @kb.add("c-v")
    def _(event):  # type: ignore
        """Paste image from clipboard as [Image #N]."""
        tag = capture_clipboard_tag()
        if tag:
            with contextlib.suppress(Exception):
                event.current_buffer.insert_text(tag)  # pyright: ignore[reportUnknownMemberType]

    @kb.add("enter")
    def _(event):  # type: ignore
        buf = event.current_buffer  # type: ignore
        doc = buf.document  # type: ignore

        # If VS Code/Windsurf/Cursor sent a "\\" sentinel before Enter (Shift+Enter mapping),
        # treat it as a request for a newline instead of submit.
        # This allows Shift+Enter to insert a newline in our multiline prompt.
        try:
            if doc.text_before_cursor.endswith("\\"):  # type: ignore[reportUnknownMemberType]
                buf.delete_before_cursor()  # remove the sentinel backslash  # type: ignore[reportUnknownMemberType]
                buf.insert_text("\n")  # type: ignore[reportUnknownMemberType]
                return
        except Exception:
            # Fall through to default behavior if anything goes wrong
            pass

        # If the entire buffer is whitespace-only, insert a newline rather than submitting.
        if len(buf.text.strip()) == 0:  # type: ignore
            buf.insert_text("\n")  # type: ignore
            return

        # No need to persist manifest anymore - iter_inputs will handle image extraction
        buf.validate_and_handle()  # type: ignore

    @kb.add("c-j")
    def _(event):  # type: ignore
        event.current_buffer.insert_text("\n")  # type: ignore

    @kb.add("c")
    def _(event):  # type: ignore
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

    @kb.add("backspace")
    def _(event):  # type: ignore
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
                text_before_str = cast(str, text_before or "")
                if text_before_str.strip().startswith("/") and " " not in text_before_str:
                    should_refresh = True

            if should_refresh:
                buf.start_completion(select_first=False)  # type: ignore[reportUnknownMemberType]
        except Exception:
            pass

    @kb.add("left")
    def _(event):  # type: ignore
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
        except Exception:
            pass

    @kb.add("right")
    def _(event):  # type: ignore
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
        except Exception:
            pass

    return kb
