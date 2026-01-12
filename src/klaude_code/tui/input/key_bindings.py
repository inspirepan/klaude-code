"""REPL keyboard bindings for prompt_toolkit.

This module provides the factory function to create key bindings for the REPL input,
with dependencies injected to avoid circular imports.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Always, Condition, Filter
from prompt_toolkit.filters.app import has_completions, is_searching
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.keys import Keys

from klaude_code.tui.input.drag_drop import convert_dropped_text
from klaude_code.tui.input.paste import expand_paste_markers, store_paste


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using platform-specific commands."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
        else:
            # Linux: try xclip first, then xsel
            if shutil.which("xclip"):
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    check=True,
                )
            elif shutil.which("xsel"):
                subprocess.run(
                    ["xsel", "--clipboard", "--input"],
                    input=text.encode("utf-8"),
                    check=True,
                )
    except (OSError, subprocess.SubprocessError):
        pass


def create_key_bindings(
    capture_clipboard_tag: Callable[[], str | None],
    at_token_pattern: re.Pattern[str],
    *,
    input_enabled: Filter | None = None,
    open_model_picker: Callable[[], None] | None = None,
    open_thinking_picker: Callable[[], None] | None = None,
) -> KeyBindings:
    """Create REPL key bindings with injected dependencies.

    Args:
        capture_clipboard_tag: Callable to capture clipboard image and return [image ...] marker
        at_token_pattern: Pattern to match @token for completion refresh

    Returns:
        KeyBindings instance with all REPL handlers configured
    """
    kb = KeyBindings()
    enabled = input_enabled if input_enabled is not None else Always()

    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    swallow_next_control_j = False

    def _is_bash_mode_text(text: str) -> bool:
        return text.startswith(("!", "！"))

    def _data_requests_newline(data: str) -> bool:
        """Return True when incoming key data should insert a newline.

        Different terminals and editor-integrated terminals can emit different
        sequences for Shift+Enter/Alt+Enter. We treat these as "insert newline"
        instead of "submit".
        """

        if not data:
            return False

        # Pure LF or LF-prefixed sequences (e.g. when modifiers are encoded).
        if data == "\n" or (ord(data[0]) == 10 and len(data) > 1):
            return True

        # Known escape sequences observed in some terminals.
        if data in {
            "\x1b\r",  # Alt+Enter (ESC + CR)
            "\x1b[13;2~",  # Shift+Enter (some terminals)
            "\x1b[27;2;13~",  # Shift+Enter (xterm "CSI 27" modified keys)
            "\\\r",  # Backslash+Enter sentinel (some editor terminals)
        }:
            return True

        # Any payload that contains both ESC and CR.
        return len(data) > 1 and "\x1b" in data and "\r" in data

    def _insert_newline(event: KeyPressEvent, *, strip_trailing_backslash: bool = False) -> None:
        buf = event.current_buffer
        if strip_trailing_backslash:
            try:
                doc = buf.document  # type: ignore[reportUnknownMemberType]
                if doc.text_before_cursor.endswith("\\"):  # type: ignore[reportUnknownMemberType]
                    buf.delete_before_cursor()  # type: ignore[reportUnknownMemberType]
            except Exception:
                pass

        with contextlib.suppress(Exception):
            buf.insert_text("\n")  # type: ignore[reportUnknownMemberType]
        with contextlib.suppress(Exception):
            event.app.invalidate()  # type: ignore[reportUnknownMemberType]

    def _can_move_cursor_visually_within_wrapped_line(delta_visible_y: int) -> bool:
        """Return True when Up/Down should move within a wrapped visual line.

        prompt_toolkit's default Up/Down behavior operates on logical lines
        (split by '\n'). When a single logical line wraps across terminal
        rows, pressing Up/Down should move within those wrapped rows instead of
        triggering history navigation.

        We only intercept when the cursor can move to an adjacent *visible*
        line that maps to the same input line.
        """

        try:
            app = get_app()
            window = app.layout.current_window
            ri = window.render_info
            if ri is None:
                return False

            current_visible_y = int(ri.cursor_position.y)
            target_visible_y = current_visible_y + delta_visible_y
            if target_visible_y < 0:
                return False

            current_input_line = ri.visible_line_to_input_line.get(current_visible_y)
            target_input_line = ri.visible_line_to_input_line.get(target_visible_y)
            return current_input_line is not None and current_input_line == target_input_line
        except Exception:
            return False

    def _move_cursor_visually_within_wrapped_line(event: KeyPressEvent, *, delta_visible_y: int) -> None:
        """Move the cursor Up/Down by one wrapped screen row, keeping column."""

        buf = event.current_buffer
        try:
            window = event.app.layout.current_window
            ri = window.render_info
            if ri is None:
                return

            rowcol_to_yx = getattr(ri, "_rowcol_to_yx", None)
            x_offset = getattr(ri, "_x_offset", None)
            y_offset = getattr(ri, "_y_offset", None)
            if not isinstance(rowcol_to_yx, dict) or not isinstance(x_offset, int) or not isinstance(y_offset, int):
                return
            rowcol_to_yx_typed = cast(dict[tuple[int, int], tuple[int, int]], rowcol_to_yx)

            current_visible_y = int(ri.cursor_position.y)
            target_visible_y = current_visible_y + delta_visible_y
            mapping = ri.visible_line_to_row_col
            if current_visible_y not in mapping or target_visible_y not in mapping:
                return

            current_row, _ = mapping[current_visible_y]
            target_row, _ = mapping[target_visible_y]

            # Only handle wrapped rows within the same input line.
            if current_row != target_row:
                return

            current_abs_y = y_offset + current_visible_y
            target_abs_y = y_offset + target_visible_y
            cursor_abs_x = x_offset + int(ri.cursor_position.x)

            def _segment_start_abs_x(row: int, abs_y: int) -> int | None:
                xs: list[int] = []
                for (r, _col), (y, x) in rowcol_to_yx_typed.items():
                    if r == row and y == abs_y:
                        xs.append(x)
                return min(xs) if xs else None

            current_start_x = _segment_start_abs_x(current_row, current_abs_y)
            target_start_x = _segment_start_abs_x(target_row, target_abs_y)
            if current_start_x is None or target_start_x is None:
                return

            offset_in_segment_cells = max(0, cursor_abs_x - current_start_x)
            desired_abs_x = target_start_x + offset_in_segment_cells

            candidates: list[tuple[int, int]] = []
            for (r, col), (y, x) in rowcol_to_yx_typed.items():
                if r == target_row and y == target_abs_y:
                    candidates.append((col, x))
            if not candidates:
                return

            # Pick the closest column at/before the desired X. If the desired
            # position is before the first character, snap to the first.
            candidates.sort(key=lambda t: t[1])
            chosen_display_col = candidates[0][0]
            for col, x in candidates:
                if x <= desired_abs_x:
                    chosen_display_col = col
                else:
                    break

            control = event.app.layout.current_control
            get_processed_line = getattr(control, "_last_get_processed_line", None)
            target_source_col = chosen_display_col
            if callable(get_processed_line):
                processed_line = get_processed_line(target_row)
                display_to_source = getattr(processed_line, "display_to_source", None)
                if callable(display_to_source):
                    display_to_source_fn = cast(Callable[[int], int], display_to_source)
                    target_source_col = display_to_source_fn(chosen_display_col)

            doc = buf.document  # type: ignore[reportUnknownMemberType]
            new_index = doc.translate_row_col_to_index(target_row, target_source_col)  # type: ignore[reportUnknownMemberType]
            buf.cursor_position = new_index  # type: ignore[reportUnknownMemberType]
            event.app.invalidate()  # type: ignore[reportUnknownMemberType]
        except Exception:
            return

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
        """Paste image from clipboard as an `[image ...]` marker."""
        marker = capture_clipboard_tag()
        if marker:
            with contextlib.suppress(Exception):
                event.current_buffer.insert_text(marker)  # pyright: ignore[reportUnknownMemberType]

    @kb.add(Keys.BracketedPaste, filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Handle bracketed paste.

        - Large multi-line pastes are folded into a marker: `[paste #N ...]`.
        - Otherwise, try to convert dropped file URLs/paths into @ tokens or `[image ...]` markers.
        """

        data = getattr(event, "data", "")
        if not isinstance(data, str) or not data:
            return

        pasted_lines = data.splitlines()
        line_count = max(1, len(pasted_lines))
        total_chars = len(data)

        should_fold = line_count > 10 or total_chars > 1000
        if should_fold:
            marker = store_paste(data)
            if marker and not marker.endswith((" ", "\t", "\n")):
                marker += " "
            with contextlib.suppress(Exception):
                event.current_buffer.insert_text(marker)  # pyright: ignore[reportUnknownMemberType]
            return

        converted = convert_dropped_text(data, cwd=Path.cwd())
        if converted != data and converted and not converted.endswith((" ", "\t", "\n")):
            converted += " "

        buf = event.current_buffer
        try:
            if buf.selection_state:  # type: ignore[reportUnknownMemberType]
                buf.cut_selection()  # type: ignore[reportUnknownMemberType]
        except Exception:
            pass

        with contextlib.suppress(Exception):
            buf.insert_text(converted)  # type: ignore[reportUnknownMemberType]

    @kb.add("escape", "enter", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Alt+Enter inserts a newline."""

        _insert_newline(event)

    @kb.add("escape", "[", "1", "3", ";", "2", "~", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Shift+Enter sequence used by some terminals inserts a newline."""

        _insert_newline(event)

    @kb.add("enter", filter=enabled & ~is_searching)
    def _(event: KeyPressEvent) -> None:
        nonlocal swallow_next_control_j

        buf = event.current_buffer
        doc = buf.document  # type: ignore

        # Normalize a leading full-width exclamation mark to ASCII so that:
        # - UI echo shows `!cmd` consistently
        # - history stores `!cmd` (not `！cmd`)
        # - bash-mode detection is stable
        try:
            current_text = buf.text  # type: ignore[reportUnknownMemberType]
            cursor_pos = int(buf.cursor_position)  # type: ignore[reportUnknownMemberType]
        except Exception:
            current_text = ""
            cursor_pos = 0

        if current_text.startswith("！"):
            normalized = "!" + current_text[1:]
            if normalized != current_text:
                with contextlib.suppress(Exception):
                    buf.text = normalized  # type: ignore[reportUnknownMemberType]
                    buf.cursor_position = min(cursor_pos, len(normalized))  # type: ignore[reportUnknownMemberType]
                current_text = normalized

        # Bash mode: if there is no command after `!` (ignoring only space/tab),
        # ignore Enter but keep the input text as-is.
        if _is_bash_mode_text(current_text):
            after_bang = current_text[1:]
            command = after_bang.lstrip(" \t")
            if command == "":
                return

        data = getattr(event, "data", "")
        if isinstance(data, str) and _data_requests_newline(data):
            _insert_newline(event)
            return

        # VS Code-family terminals often implement Shift+Enter via a "\\" sentinel
        # before Enter. Only enable this heuristic under TERM_PROGRAM=vscode.
        if term_program == "vscode":
            try:
                if doc.text_before_cursor.endswith("\\"):  # type: ignore[reportUnknownMemberType]
                    swallow_next_control_j = True
                    _insert_newline(event, strip_trailing_backslash=True)
                    return
            except (AttributeError, TypeError):
                pass

        # When completions are visible, Enter accepts the current selection.
        # This aligns with common TUI completion UX: navigation doesn't modify
        # the buffer, and Enter/Tab inserts the selected option.
        #
        # Bash mode disables completions entirely, so always prefer submitting.
        if (
            not _is_bash_mode_text(current_text)
            and not _should_submit_instead_of_accepting_completion(buf)
            and _accept_current_completion(buf)
        ):
            return

        # Before submitting, expand any folded paste markers so that:
        # - the actual request contains the full pasted content
        # - prompt_toolkit history stores the expanded content
        # Also convert any remaining file:// drops that bypassed bracketed paste.
        try:
            current_text = buf.text  # type: ignore[reportUnknownMemberType]
        except Exception:
            current_text = ""
        prepared = expand_paste_markers(current_text)
        prepared = convert_dropped_text(prepared, cwd=Path.cwd())
        if prepared != current_text:
            with contextlib.suppress(Exception):
                buf.text = prepared  # type: ignore[reportUnknownMemberType]
                buf.cursor_position = len(prepared)  # type: ignore[reportUnknownMemberType]

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

    @kb.add(
        "up",
        filter=enabled
        & ~has_completions
        & Condition(lambda: _can_move_cursor_visually_within_wrapped_line(delta_visible_y=-1)),
        eager=True,
    )
    def _(event: KeyPressEvent) -> None:
        _move_cursor_visually_within_wrapped_line(event, delta_visible_y=-1)

    @kb.add(
        "down",
        filter=enabled
        & ~has_completions
        & Condition(lambda: _can_move_cursor_visually_within_wrapped_line(delta_visible_y=1)),
        eager=True,
    )
    def _(event: KeyPressEvent) -> None:
        _move_cursor_visually_within_wrapped_line(event, delta_visible_y=1)

    @kb.add("c-j", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        nonlocal swallow_next_control_j
        if swallow_next_control_j:
            swallow_next_control_j = False
            return

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
                copy_to_clipboard(selected_text)
            buf.exit_selection()  # type: ignore[reportUnknownMemberType]
        else:
            buf.insert_text("c")  # type: ignore[reportUnknownMemberType]

    @kb.add("backspace", filter=enabled)
    def _(event: KeyPressEvent) -> None:
        """Ensure completions refresh on backspace when editing an @token.

        We delete the character before cursor (default behavior), then explicitly
        trigger completion refresh if the caret is still within an @… token.
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

    @kb.add("escape", "up", filter=enabled & ~has_completions)
    def _(event: KeyPressEvent) -> None:
        """Option+Up switches to previous history entry."""
        event.current_buffer.history_backward()

    @kb.add("escape", "down", filter=enabled & ~has_completions)
    def _(event: KeyPressEvent) -> None:
        """Option+Down switches to next history entry."""
        event.current_buffer.history_forward()

    return kb
