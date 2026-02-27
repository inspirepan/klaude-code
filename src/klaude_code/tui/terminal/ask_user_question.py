from __future__ import annotations

import contextlib
import sys
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Always, Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.containers import Container, ScrollOffsets
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style, merge_styles
from prompt_toolkit.styles.base import BaseStyle

from klaude_code.tui.terminal.selector import (
    QuestionPrompt,
    QuestionSelectResult,
    SelectItem,
)


def _restyle_title(title: list[tuple[str, str]], cls: str) -> list[tuple[str, str]]:
    """Re-apply a style class while keeping existing style tokens."""

    keep_attrs = {"bold", "italic", "underline", "reverse", "blink", "strike", "dim"}
    restyled: list[tuple[str, str]] = []
    for old_style, text in title:
        tokens = old_style.split()
        attrs = [tok for tok in tokens if tok in keep_attrs]
        style_tokens = [tok for tok in tokens if tok not in keep_attrs]

        if cls in style_tokens:
            style_tokens = [tok for tok in style_tokens if tok != cls]

        combined = [cls, *style_tokens, *attrs]
        style = " ".join(tok for tok in combined if tok)
        restyled.append((style, text))
    return restyled


def _indent_multiline_tokens(
    tokens: list[tuple[str, str]],
    indent: str,
    *,
    indent_style: str = "class:text",
) -> list[tuple[str, str]]:
    """Indent continuation lines inside formatted tokens."""
    if not tokens or all("\n" not in text for _style, text in tokens):
        return tokens

    def _has_non_newline_text(s: str) -> bool:
        return bool(s.replace("\n", ""))

    has_text_after_token: list[bool] = [False] * len(tokens)
    remaining = False
    for i in range(len(tokens) - 1, -1, -1):
        has_text_after_token[i] = remaining
        remaining = remaining or _has_non_newline_text(tokens[i][1])

    out: list[tuple[str, str]] = []
    for token_index, (style, text) in enumerate(tokens):
        if "\n" not in text:
            out.append((style, text))
            continue

        parts = text.split("\n")
        for part_index, part in enumerate(parts):
            if part:
                out.append((style, part))

            if part_index < len(parts) - 1:
                out.append((style, "\n"))

                has_text_later_in_token = any(p for p in parts[part_index + 1 :])
                if has_text_later_in_token or has_text_after_token[token_index]:
                    out.append((indent_style, indent))

    return out


def _split_title_number_prefix(
    tokens: list[tuple[str, str]],
    row_num_text: str,
) -> tuple[tuple[str, str] | None, list[tuple[str, str]]]:
    """Split leading row number token from title tokens when present."""
    if not tokens:
        return None, tokens

    first_style, first_text = tokens[0]
    if not first_text.startswith(row_num_text):
        return None, tokens

    remainder = first_text[len(row_num_text) :]
    if remainder:
        return (first_style, row_num_text), [(first_style, remainder), *tokens[1:]]
    return (first_style, row_num_text), tokens[1:]


def select_questions[T](
    *,
    questions: list[QuestionPrompt[T]],
    pointer: str = "→",
    style: BaseStyle | None = None,
) -> list[QuestionSelectResult[T]] | None:
    """Render multiple question prompts in one panel.

    - Up/Down move within current tab
    - Left/Right and Tab switch tabs
    - Enter confirms current single-select question and moves to next tab
    - For multi-select: Enter toggles current option; use per-question Submit row to confirm
    - When there are multiple questions, a final Submit tab performs submit/cancel
    """
    if not questions:
        return None
    if any(not question.items for question in questions):
        return None

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    has_submit_tab = len(questions) > 1
    submit_tab_idx = len(questions) if has_submit_tab else None
    active_tab_idx = 0
    pointed_at_by_question = [0 for _ in questions]
    selected_indices_by_question: list[set[int]] = [set() for _ in questions]
    input_text_by_question = ["" for _ in questions]
    confirmed_results: list[QuestionSelectResult[T]] = [
        QuestionSelectResult(selected_values=[], input_text="") for _ in questions
    ]
    answered_by_question = [False for _ in questions]
    submit_pointed_at = 0
    submit_warning = False
    input_buffer = Buffer()

    def _is_submit_tab(tab_idx: int | None = None) -> bool:
        if submit_tab_idx is None:
            return False
        idx = active_tab_idx if tab_idx is None else tab_idx
        return idx == submit_tab_idx

    def _current_question_idx() -> int:
        if _is_submit_tab():
            return 0
        return active_tab_idx

    def _current_question() -> QuestionPrompt[T]:
        return questions[_current_question_idx()]

    def _is_input_row(row: int, *, question_idx: int | None = None) -> bool:
        idx = _current_question_idx() if question_idx is None else question_idx
        return row == len(questions[idx].items)

    def _question_submit_row_index(question_idx: int) -> int | None:
        question = questions[question_idx]
        if not question.multi_select:
            return None
        return len(question.items) + 1

    def _is_question_submit_row(row: int, *, question_idx: int | None = None) -> bool:
        idx = _current_question_idx() if question_idx is None else question_idx
        submit_row = _question_submit_row_index(idx)
        return submit_row is not None and row == submit_row

    def _total_rows(question_idx: int) -> int:
        submit_row = _question_submit_row_index(question_idx)
        if submit_row is None:
            return len(questions[question_idx].items) + 1
        return submit_row + 1

    def _switch_tab(delta: int) -> None:
        nonlocal active_tab_idx, submit_warning
        if not _is_submit_tab(active_tab_idx):
            input_text_by_question[active_tab_idx] = input_buffer.text

        tab_count = len(questions) + (1 if has_submit_tab else 0)
        active_tab_idx = (active_tab_idx + delta) % tab_count
        submit_warning = False

        if _is_submit_tab(active_tab_idx):
            return

        input_buffer.text = input_text_by_question[active_tab_idx]
        input_buffer.cursor_position = len(input_buffer.text)

    def _move(delta: int) -> None:
        nonlocal submit_pointed_at
        if _is_submit_tab():
            submit_pointed_at = (submit_pointed_at + delta) % 2
            return

        question_idx = _current_question_idx()
        pointed = pointed_at_by_question[question_idx]
        total_rows = _total_rows(question_idx)
        pointed_at_by_question[question_idx] = (pointed + delta) % total_rows

    def _toggle_current_option() -> None:
        if _is_submit_tab():
            return

        question_idx = _current_question_idx()
        row = pointed_at_by_question[question_idx]
        if _is_input_row(row, question_idx=question_idx) or _is_question_submit_row(row, question_idx=question_idx):
            return

        selected_indices = selected_indices_by_question[question_idx]
        idx = pointed_at_by_question[question_idx]
        if _current_question().multi_select:
            if idx in selected_indices:
                selected_indices.remove(idx)
            else:
                selected_indices.add(idx)
            return

        selected_indices_by_question[question_idx] = {idx}

    def _build_draft_result_for(question_idx: int) -> QuestionSelectResult[T]:
        question = questions[question_idx]
        effective: set[int] = set(selected_indices_by_question[question_idx])
        pointed_at = pointed_at_by_question[question_idx]
        if (
            not question.multi_select
            and not effective
            and not _is_input_row(pointed_at, question_idx=question_idx)
            and not _is_question_submit_row(pointed_at, question_idx=question_idx)
        ):
            effective = {pointed_at}

        values: list[T] = []
        for idx in sorted(effective):
            value = question.items[idx].value
            if value is None:
                continue
            values.append(value)

        if _is_submit_tab(active_tab_idx):
            input_text = input_text_by_question[question_idx]
        elif question_idx == active_tab_idx:
            input_text = input_buffer.text
        else:
            input_text = input_text_by_question[question_idx]

        if question.other_value is not None and question.other_value not in values and input_text.strip():
            values.append(question.other_value)

        return QuestionSelectResult(selected_values=values, input_text=input_text)

    def _has_answer(result: QuestionSelectResult[T]) -> bool:
        return bool(result.selected_values or result.input_text.strip())

    def _confirm_current_question() -> None:
        if _is_submit_tab():
            return

        question_idx = _current_question_idx()
        input_text_by_question[question_idx] = input_buffer.text
        result = _build_draft_result_for(question_idx)
        confirmed_results[question_idx] = result
        answered_by_question[question_idx] = _has_answer(result)

    def _all_answered() -> bool:
        return all(answered_by_question)

    def _confirmed_results() -> list[QuestionSelectResult[T]]:
        return [confirmed_results[i] for i in range(len(questions))]

    def _find_item_by_value(question: QuestionPrompt[T], value: T) -> SelectItem[T] | None:
        for item in question.items:
            if item.value == value:
                return item
        return None

    def _answer_summary(question_idx: int) -> str:
        result = confirmed_results[question_idx]
        if not answered_by_question[question_idx]:
            return "(No answer provided)"

        question = questions[question_idx]
        parts: list[str] = []
        for value in result.selected_values:
            if question.other_value is not None and value == question.other_value:
                other_text = result.input_text.strip()
                parts.append(f"Other: {other_text}" if other_text else "Other")
                continue

            item = _find_item_by_value(question, value)
            if item is None:
                parts.append(str(value))
                continue
            parts.append(item.summary or str(item.value))

        if not parts and result.input_text.strip():
            parts.append(f"Other: {result.input_text.strip()}")

        return ", ".join(parts) if parts else "(No answer provided)"

    def get_tabs_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        if has_submit_tab:
            tokens.append(("class:meta", "← "))
        for idx, question in enumerate(questions):
            tab_style = "class:question_tab_active" if idx == active_tab_idx else "class:question_tab_inactive"
            check = "☒" if answered_by_question[idx] else "☐"
            tokens.append((tab_style, f" {check} {question.header} "))
            tokens.append(("class:text", " "))

        if has_submit_tab:
            submit_style = "class:question_tab_active" if _is_submit_tab() else "class:question_tab_inactive"
            tokens.append((submit_style, " ✔ Submit "))
            tokens.append(("class:meta", " → · Enter to confirm"))
        else:
            tokens.append(("class:meta", " → · Enter to confirm"))
        return tokens

    def get_header_tokens() -> list[tuple[str, str]]:
        if _is_submit_tab():
            return [("class:question", "Review your answers")]
        return [("class:question", _current_question().message + " ")]

    def _trim_last_newline(title_tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not title_tokens:
            return title_tokens
        last_style, last_text = title_tokens[-1]
        if not last_text.endswith("\n"):
            return title_tokens
        trimmed = last_text[:-1]
        return [*title_tokens[:-1], (last_style, trimmed)] if trimmed else title_tokens[:-1]

    def _build_question_choices_tokens(question_idx: int) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "

        question = questions[question_idx]
        pointed_at = pointed_at_by_question[question_idx]
        selected_indices = selected_indices_by_question[question_idx]

        for idx, item in enumerate(question.items):
            is_pointed = pointed_at == idx
            if is_pointed:
                tokens.append(("class:pointer", pointed_prefix))
            else:
                tokens.append(("class:text", pointer_pad))

            title_tokens = _restyle_title(item.title, "class:highlighted") if is_pointed else item.title
            row_num_text = f"{idx + 1}. "
            row_num_token, title_tokens_without_num = _split_title_number_prefix(title_tokens, row_num_text)

            if question.multi_select and row_num_token is not None:
                tokens.append(row_num_token)
                is_selected = idx in selected_indices
                marker = "[✔] " if is_selected else "[ ] "
                marker_style = "class:highlighted" if is_selected else "class:text"
                tokens.append((marker_style, marker))
                title_tokens = title_tokens_without_num
            elif question.multi_select:
                is_selected = idx in selected_indices
                marker = "[✔] " if is_selected else "[ ] "
                marker_style = "class:highlighted" if is_selected else "class:text"
                tokens.append((marker_style, marker))

            if idx == len(question.items) - 1:
                title_tokens = _trim_last_newline(title_tokens)
            tokens.extend(_indent_multiline_tokens(title_tokens, pointer_pad))

        return tokens

    def _build_submit_choices_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "

        for idx, question in enumerate(questions):
            tokens.append(("class:msg", f" ● {question.message}\n"))
            summary_style = "class:highlighted" if answered_by_question[idx] else "class:warning"
            tokens.append(("class:meta", "   → "))
            tokens.append((summary_style, f"{_answer_summary(idx)}\n"))

        tokens.append(("class:text", "\n"))
        if _all_answered():
            tokens.append(("class:question", "Ready to submit your answers?\n\n"))
        else:
            tokens.append(("class:warning", "You have not answered all questions\n\n"))

        options = ["Submit answers", "Cancel"]
        for idx, option in enumerate(options, start=1):
            is_pointed = submit_pointed_at == idx - 1
            if is_pointed:
                tokens.append(("class:pointer", pointed_prefix))
                tokens.append(("class:highlighted", f"{idx}. {option}\n"))
            else:
                tokens.append(("class:text", pointer_pad))
                tokens.append(("class:text", f"{idx}. {option}\n"))

        if submit_warning:
            tokens.append(("class:warning", "\nYou have not answered all questions"))

        return tokens

    def get_choices_tokens() -> list[tuple[str, str]]:
        if _is_submit_tab():
            return _build_submit_choices_tokens()
        return _build_question_choices_tokens(_current_question_idx())

    def get_input_prefix_tokens() -> list[tuple[str, str]]:
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "
        question_idx = _current_question_idx()
        question = _current_question()
        row_num = f"{len(question.items) + 1}. "
        is_input_row = (not _is_submit_tab()) and _is_input_row(pointed_at_by_question[question_idx])
        row_style = "class:highlighted" if is_input_row else "class:msg"

        prefix: list[tuple[str, str]] = []
        if is_input_row:
            prefix.append(("class:pointer", pointed_prefix))
        else:
            prefix.append(("class:text", pointer_pad))

        if question.multi_select and question.other_value is not None:
            prefix.append((row_style, row_num))
            is_selected = bool(input_buffer.text.strip())
            marker = "[✔] " if is_selected else "[ ] "
            marker_style = "class:highlighted" if is_selected else "class:text"
            prefix.append((marker_style, marker))
            return prefix

        prefix.append((row_style, row_num))
        return prefix

    def get_other_label_tokens() -> list[tuple[str, str]]:
        is_pointed = (not _is_submit_tab()) and _is_input_row(pointed_at_by_question[_current_question_idx()])
        style_name = "class:highlighted" if is_pointed else "class:msg"
        return [(style_name, "Other: ")]

    def get_question_submit_tokens() -> list[tuple[str, str]]:
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "
        question_idx = _current_question_idx()
        is_pointed = _is_question_submit_row(pointed_at_by_question[question_idx], question_idx=question_idx)
        if is_pointed:
            return [("class:pointer", pointed_prefix), ("class:highlighted class:submit_option", " ✔  Submit")]
        return [("class:text", pointer_pad), ("class:submit_option", " ✔  Submit")]

    def get_input_placeholder_tokens() -> list[tuple[str, str]]:
        placeholder = _current_question().input_placeholder
        style_name = (
            "class:highlighted"
            if not _is_submit_tab() and _is_input_row(pointed_at_by_question[_current_question_idx()])
            else "class:search_placeholder"
        )
        return [(style_name, placeholder)]

    kb = KeyBindings()

    @kb.add(Keys.ControlC, eager=True)
    @kb.add(Keys.ControlQ, eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    @kb.add(Keys.Left, eager=True)
    def _(event: KeyPressEvent) -> None:
        _switch_tab(-1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.Right, eager=True)
    def _(event: KeyPressEvent) -> None:
        _switch_tab(+1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.Tab, eager=True)
    def _(event: KeyPressEvent) -> None:
        _switch_tab(+1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.BackTab, eager=True)
    def _(event: KeyPressEvent) -> None:
        _switch_tab(-1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.Down, eager=True)
    def _(event: KeyPressEvent) -> None:
        _move(+1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.Up, eager=True)
    def _(event: KeyPressEvent) -> None:
        _move(-1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(
        " ",
        eager=True,
        filter=Condition(
            lambda: (not _is_submit_tab()) and _is_question_submit_row(pointed_at_by_question[_current_question_idx()])
        ),
    )
    def _(event: KeyPressEvent) -> None:
        _confirm_current_question()
        if not has_submit_tab:
            event.app.exit(result=_confirmed_results())
            return
        _switch_tab(+1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(
        " ",
        eager=True,
        filter=Condition(
            lambda: (not _is_submit_tab())
            and (not _is_input_row(pointed_at_by_question[_current_question_idx()]))
            and (not _is_question_submit_row(pointed_at_by_question[_current_question_idx()]))
        ),
    )
    def _(event: KeyPressEvent) -> None:
        _toggle_current_option()
        event.app.invalidate()

    @kb.add(Keys.Enter, eager=True)
    def _(event: KeyPressEvent) -> None:
        nonlocal submit_warning
        if _is_submit_tab():
            if submit_pointed_at == 0:
                if not _all_answered():
                    submit_warning = True
                    event.app.invalidate()
                    return
                event.app.exit(result=_confirmed_results())
                return
            event.app.exit(result=None)
            return

        question_idx = _current_question_idx()
        question = questions[question_idx]
        row = pointed_at_by_question[question_idx]

        if question.multi_select:
            if _is_question_submit_row(row, question_idx=question_idx):
                _confirm_current_question()
                if not has_submit_tab:
                    event.app.exit(result=_confirmed_results())
                    return
                _switch_tab(+1)
                _sync_focus(event.app)
                event.app.invalidate()
                return
            if _is_input_row(row, question_idx=question_idx):
                event.app.invalidate()
                return
            _toggle_current_option()
            event.app.invalidate()
            return

        _confirm_current_question()
        if not has_submit_tab:
            event.app.exit(result=_confirmed_results())
            return
        _switch_tab(+1)
        _sync_focus(event.app)
        event.app.invalidate()

    @kb.add(Keys.Escape, eager=True)
    def _(event: KeyPressEvent) -> None:
        if (
            not _is_submit_tab()
            and _is_input_row(pointed_at_by_question[_current_question_idx()])
            and input_buffer.text
        ):
            input_buffer.text = ""
            event.app.invalidate()
            return
        event.app.exit(result=None)

    tabs_window = Window(
        FormattedTextControl(get_tabs_tokens),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    top_spacer_window = Window(
        FormattedTextControl([("", "")]),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    tabs_header_spacer_window = Window(
        FormattedTextControl([("", "")]),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    header_window = Window(
        FormattedTextControl(get_header_tokens),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    spacer_window = Window(
        FormattedTextControl([("", "")]),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    list_control = FormattedTextControl(get_choices_tokens, focusable=True)
    list_window = Window(
        list_control,
        scroll_offsets=ScrollOffsets(top=1, bottom=2),
        allow_scroll_beyond_bottom=True,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )

    max_row_num = max(len(question.items) + 1 for question in questions)
    has_multi_select_other_question = any(
        question.multi_select and question.other_value is not None for question in questions
    )
    input_prefix_template = f" {pointer} " + f"{max_row_num}. " + ("[ ] " if has_multi_select_other_question else "")
    input_prefix_window = Window(
        FormattedTextControl(get_input_prefix_tokens),
        width=max(1, len(input_prefix_template)),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    other_label_window = Window(
        FormattedTextControl(get_other_label_tokens),
        width=len("Other: "),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    input_text_window = Window(
        BufferControl(buffer=input_buffer),
        height=1,
        dont_extend_height=Always(),
    )
    input_placeholder_window = ConditionalContainer(
        content=Window(
            FormattedTextControl(get_input_placeholder_tokens),
            height=1,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        ),
        filter=Condition(lambda: input_buffer.text == ""),
    )
    input_container = FloatContainer(
        content=input_text_window,
        floats=[Float(content=input_placeholder_window, top=0, left=0)],
    )
    input_row = VSplit([input_prefix_window, other_label_window, input_container], padding=0)
    input_row_container = ConditionalContainer(content=input_row, filter=Condition(lambda: not _is_submit_tab()))
    question_submit_spacer_container = ConditionalContainer(
        content=Window(
            FormattedTextControl([("", "")]),
            height=1,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        ),
        filter=Condition(lambda: (not _is_submit_tab()) and _current_question().multi_select),
    )
    question_submit_row_container = ConditionalContainer(
        content=Window(
            FormattedTextControl(get_question_submit_tokens),
            height=1,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        ),
        filter=Condition(lambda: (not _is_submit_tab()) and _current_question().multi_select),
    )

    def _sync_focus(app: Application[Any]) -> None:
        if _is_submit_tab():
            target = list_window
        else:
            question_idx = _current_question_idx()
            target = (
                input_text_window
                if _is_input_row(pointed_at_by_question[question_idx], question_idx=question_idx)
                else list_window
            )
        if app.layout.current_window is not target:
            app.layout.focus(target)

    def _on_input_changed(_: Buffer) -> None:
        with contextlib.suppress(Exception):
            app = get_app()
            app.invalidate()

    input_buffer.on_text_changed += _on_input_changed

    input_buffer.text = input_text_by_question[_current_question_idx()]

    root_children: list[Container] = [top_spacer_window, tabs_window, tabs_header_spacer_window]
    root_children.extend(
        [
            header_window,
            spacer_window,
            list_window,
            input_row_container,
            question_submit_spacer_container,
            question_submit_row_container,
        ]
    )
    root = HSplit(root_children)

    def _before_render(app: Application[list[QuestionSelectResult[T]] | None]) -> None:
        _sync_focus(app)

    base_style = Style(
        [
            ("frame.border", "fg:ansibrightblack dim"),
            ("frame.label", "fg:ansibrightblack italic"),
            ("search_placeholder", "fg:ansibrightblack italic"),
            ("question_tab_inactive", "reverse fg:ansibrightblack"),
            ("question_tab_active", "reverse fg:ansigreen bold"),
            ("warning", "fg:ansiyellow"),
            ("submit_option", "bold"),
        ]
    )
    merged_style = merge_styles([base_style, style] if style is not None else [base_style])

    app: Application[list[QuestionSelectResult[T]] | None] = Application(
        layout=Layout(root, focused_element=list_window),
        key_bindings=merge_key_bindings([load_key_bindings(), kb]),
        style=merged_style,
        mouse_support=False,
        full_screen=False,
        erase_when_done=True,
        before_render=_before_render,
    )
    app.renderer.cpr_not_supported_callback = lambda: None
    return app.run()


def select_question[T](
    *,
    message: str,
    items: list[SelectItem[T]],
    multi_select: bool,
    pointer: str = "→",
    style: BaseStyle | None = None,
    input_placeholder: str = "Type something…",
    other_value: T | None = None,
) -> QuestionSelectResult[T] | None:
    results = select_questions(
        questions=[
            QuestionPrompt(
                header="Question",
                message=message,
                items=items,
                multi_select=multi_select,
                input_placeholder=input_placeholder,
                other_value=other_value,
            )
        ],
        pointer=pointer,
        style=style,
    )
    if results is None:
        return None
    return results[0]
