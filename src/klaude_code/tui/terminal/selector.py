from __future__ import annotations

import contextlib
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

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

from klaude_code.ui.common import format_model_params

DEFAULT_PICKER_STYLE = Style(
    [
        ("pointer", "ansigreen"),
        ("highlighted", "ansigreen"),
        ("msg", ""),
        ("meta", "fg:ansibrightblack"),
        ("text", "ansibrightblack"),
        ("question", "bold"),
        ("search_prefix", "ansibrightblack"),
        # Search filter colors at the bottom (currently unused by selector, but
        # kept for consistency with picker style defaults).
        ("search_success", "noinherit fg:ansigreen"),
        ("search_none", "noinherit fg:ansired"),
    ]
)


@dataclass(frozen=True, slots=True)
class SelectItem[T]:
    """One selectable item for terminal selection UI."""

    title: list[tuple[str, str]]
    value: T | None
    search_text: str
    summary: str | None = None
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class QuestionSelectResult[T]:
    selected_values: list[T]
    input_text: str


@dataclass(frozen=True, slots=True)
class QuestionPrompt[T]:
    header: str
    message: str
    items: list[SelectItem[T]]
    multi_select: bool
    input_placeholder: str = "Type something."
    other_value: T | None = None


# ---------------------------------------------------------------------------
# Model selection items builder
# ---------------------------------------------------------------------------


def build_model_select_items(models: list[Any]) -> list[SelectItem[str]]:
    """Build SelectItem list from ModelEntry objects.

    Args:
        models: List of ModelEntry objects (from config.iter_model_entries).

    Returns:
        List of SelectItem[str] with model selector as the value.
    """
    if not models:
        return []

    max_model_name_length = max(len(m.model_name) for m in models)
    num_width = len(str(len(models)))

    # Group models by provider in stable insertion order.
    provider_grouped: dict[str, list[Any]] = {}
    for m in models:
        provider = str(getattr(m, "provider", ""))
        provider_grouped.setdefault(provider, []).append(m)

    all_groups: list[tuple[str, list[Any]]] = list(provider_grouped.items())

    # Calculate max header width for alignment across all groups.
    max_header_len = max(len(f"{name.upper()} ({len(ms)})") for name, ms in all_groups)

    items: list[SelectItem[str]] = []
    model_idx = 0
    separator_base_len = 80
    for group_name, group_models in all_groups:
        group_text = group_name.lower()
        count_text = f"({len(group_models)})"
        header_len = len(group_text) + 1 + len(count_text)
        separator_len = separator_base_len + max_header_len - header_len
        separator = "-" * separator_len
        items.append(
            SelectItem(
                title=[
                    ("class:meta ansiyellow", group_text + " "),
                    ("class:meta ansibrightblack", count_text + " "),
                    ("class:meta ansibrightblack dim", separator),
                    ("class:meta", "\n"),
                ],
                value=None,
                search_text=group_name,
                selectable=False,
            )
        )

        for m in group_models:
            model_idx += 1
            provider = str(getattr(m, "provider", ""))
            model_id_str = m.model_id or "N/A"
            display_name = m.model_name
            first_line_prefix = f"{display_name:<{max_model_name_length}}"
            meta_parts = format_model_params(m)
            meta_str = " · ".join(meta_parts) if meta_parts else ""
            title: list[tuple[str, str]] = [
                ("class:meta", f"{model_idx:>{num_width}}. "),
                ("class:msg", first_line_prefix),
                ("class:msg dim", " → "),
                ("class:msg ansiblue", model_id_str),
                ("class:msg dim", " · "),
                ("class:msg ansibrightblack", provider),
            ]

            if meta_str:
                title.append(("class:msg dim", " · "))
                title.append(("class:meta", meta_str))

            title.append(("class:meta", "\n"))
            search_text = f"{m.selector} {m.model_name} {model_id_str} {provider}"
            items.append(SelectItem(title=title, value=m.selector, search_text=search_text))

    return items


# ---------------------------------------------------------------------------
# Shared helpers for select_one() and SelectOverlay
# ---------------------------------------------------------------------------


def _restyle_title(title: list[tuple[str, str]], cls: str) -> list[tuple[str, str]]:
    """Re-apply a style class while keeping existing style tokens.

    This is used to highlight the currently-pointed item. We want to:
    - preserve explicit colors (e.g. `fg:ansibrightblack`) defined by callers
    - preserve existing classes (e.g. `class:msg`, `class:meta`) so their
      non-color attributes remain in effect
    - preserve text attributes like bold/italic/dim
    """

    keep_attrs = {"bold", "italic", "underline", "reverse", "blink", "strike", "dim"}
    restyled: list[tuple[str, str]] = []
    for old_style, text in title:
        tokens = old_style.split()
        attrs = [tok for tok in tokens if tok in keep_attrs]
        style_tokens = [tok for tok in tokens if tok not in keep_attrs]

        if cls in style_tokens:
            style_tokens = [tok for tok in style_tokens if tok != cls]

        # Place the highlight class first, so existing per-token styles (classes
        # or explicit fg/bg) keep their precedence. This prevents highlight from
        # accidentally overriding caller-defined colors.
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
    """Indent continuation lines inside formatted tokens.

    This is needed when an item's title contains embedded newlines. The selector
    prefixes each *item* with the pointer padding, but continuation lines inside
    a single item would otherwise start at column 0.
    """
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

            # If this was a newline, re-add it.
            if part_index < len(parts) - 1:
                out.append((style, "\n"))

                # Only indent when there is more text remaining within this item.
                has_text_later_in_token = any(p for p in parts[part_index + 1 :])
                if has_text_later_in_token or has_text_after_token[token_index]:
                    out.append((indent_style, indent))

    return out


def _normalize_search_key(value: str) -> str:
    """Normalize a search key for loose matching.

    This enables aliases like:
    - gpt52 -> gpt-5.2
    - gpt5.2 -> gpt-5.2

    Strategy: case-fold + keep only alphanumeric characters.
    """

    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _filter_items[T](
    items: list[SelectItem[T]],
    filter_text: str,
) -> tuple[list[int], bool]:
    """Return visible item indices and whether any matched the filter."""
    if not items:
        return [], True
    if not filter_text:
        return list(range(len(items))), True

    needle = filter_text.casefold()
    needle_norm = _normalize_search_key(filter_text)

    def _is_match(it: SelectItem[T]) -> bool:
        haystack = it.search_text.casefold()
        if needle in haystack:
            return True
        if needle_norm:
            return needle_norm in _normalize_search_key(it.search_text)
        return False

    matched_selectable = [i for i, it in enumerate(items) if it.selectable and _is_match(it)]
    if not matched_selectable:
        # Keep the full list visible so the user can still browse when the filter
        # doesn't match anything.
        return list(range(len(items))), False

    matched_set = set(matched_selectable)
    visible: list[int] = []

    # If we have non-selectable header rows, keep a header visible only when its
    # group has at least one matched selectable item.
    i = 0
    while i < len(items):
        it = items[i]
        if not it.selectable:
            header_idx = i
            group_start = i + 1
            group_end = next((j for j in range(group_start, len(items)) if not items[j].selectable), len(items))
            group_matches = [j for j in range(group_start, group_end) if j in matched_set]
            if group_matches:
                visible.append(header_idx)
                visible.extend(group_matches)
            i = group_end
            continue

        if i in matched_set:
            visible.append(i)
        i += 1

    return visible, True


def _coerce_pointed_at_to_selectable[T](
    items: list[SelectItem[T]],
    visible_indices: list[int],
    pointed_at: int,
) -> int:
    """Return a valid pointed_at position for selectable items.

    pointed_at is an index into visible_indices (not into items).
    """

    if not visible_indices:
        return 0

    start = pointed_at % len(visible_indices)
    for offset in range(len(visible_indices)):
        pos = (start + offset) % len(visible_indices)
        idx = visible_indices[pos]
        if items[idx].selectable:
            return pos
    return start


def _build_choices_tokens[T](
    items: list[SelectItem[T]],
    visible_indices: list[int],
    pointed_at: int,
    pointer: str,
    *,
    highlight_pointed_item: bool = True,
) -> list[tuple[str, str]]:
    """Build formatted tokens for the choice list."""
    if not visible_indices:
        return [("class:text", "(no items)\n")]

    tokens: list[tuple[str, str]] = []
    pointer_pad = " " * (2 + len(pointer))
    pointed_prefix = f" {pointer} "

    for pos, idx in enumerate(visible_indices):
        is_pointed = pos == pointed_at
        if is_pointed:
            tokens.append(("class:pointer", pointed_prefix))
            tokens.append(("[SetCursorPosition]", ""))
        else:
            tokens.append(("class:text", pointer_pad))

        if is_pointed and highlight_pointed_item:
            title_tokens = _restyle_title(items[idx].title, "class:highlighted")
        else:
            title_tokens = items[idx].title

        title_tokens = _indent_multiline_tokens(title_tokens, pointer_pad)
        tokens.extend(title_tokens)

    return tokens


def _build_rounded_frame(body: Container, *, padding_x: int = 0, padding_y: int = 0) -> HSplit:
    """Build a rounded border frame around the given container."""
    border = partial(Window, style="class:frame.border", height=1)
    pad = partial(Window, style="class:frame", char=" ", always_hide_cursor=Always())

    inner: Container = body
    if padding_y > 0:
        inner = HSplit(
            [
                pad(height=padding_y, dont_extend_height=Always()),
                body,
                pad(height=padding_y, dont_extend_height=Always()),
            ],
            padding=0,
            style="class:frame",
        )

    middle_children: list[Container] = [border(width=1, char="│")]
    if padding_x > 0:
        middle_children.append(pad(width=padding_x))
    middle_children.append(inner)
    if padding_x > 0:
        middle_children.append(pad(width=padding_x))
    middle_children.append(border(width=1, char="│"))

    top = VSplit(
        [
            border(width=1, char="╭"),
            border(char="─"),
            border(width=1, char="╮"),
        ],
        height=1,
        padding=0,
    )
    middle = VSplit(middle_children, padding=0)
    bottom = VSplit(
        [
            border(width=1, char="╰"),
            border(char="─"),
            border(width=1, char="╯"),
        ],
        height=1,
        padding=0,
    )
    return HSplit([top, middle, bottom], padding=0, style="class:frame")


def _build_search_container(
    search_buffer: Buffer,
    search_placeholder: str,
    *,
    frame: bool = True,
) -> tuple[Window, Container]:
    """Build the search input container with placeholder."""
    placeholder_text = f"{search_placeholder} · ↑↓ to select · enter/tab to confirm · esc to quit"

    search_prefix_window = Window(
        FormattedTextControl([("class:search_prefix", "/ ")]),
        width=2,
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    input_window = Window(
        BufferControl(buffer=search_buffer),
        height=1,
        dont_extend_height=Always(),
        style="class:search_input",
    )
    placeholder_window = ConditionalContainer(
        content=Window(
            FormattedTextControl([("class:search_placeholder", placeholder_text)]),
            height=1,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        ),
        filter=Condition(lambda: search_buffer.text == ""),
    )
    search_input_container = FloatContainer(
        content=input_window,
        floats=[Float(content=placeholder_window, top=0, left=0)],
    )
    search_row: Container = VSplit([search_prefix_window, search_input_container], padding=0)
    if frame:
        return input_window, _build_rounded_frame(search_row)
    return input_window, search_row


# ---------------------------------------------------------------------------
# select_one: standalone single-choice selector
# ---------------------------------------------------------------------------


def select_one[T](
    *,
    message: str,
    items: list[SelectItem[T]],
    pointer: str = "→",
    style: BaseStyle | None = None,
    use_search_filter: bool = True,
    initial_value: T | None = None,
    search_placeholder: str = "type to search",
    highlight_pointed_item: bool = True,
) -> T | None:
    """Terminal single-choice selector based on prompt_toolkit."""
    if not items:
        return None

    # Non-interactive environments should not enter an interactive prompt.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    pointed_at = 0

    search_buffer: Buffer | None = Buffer() if use_search_filter else None

    def get_filter_text() -> str:
        return search_buffer.text if (use_search_filter and search_buffer is not None) else ""

    def get_header_tokens() -> list[tuple[str, str]]:
        return [("class:question", message + " ")]

    def get_choices_tokens() -> list[tuple[str, str]]:
        nonlocal pointed_at
        indices, _ = _filter_items(items, get_filter_text())
        if indices:
            pointed_at = _coerce_pointed_at_to_selectable(items, indices, pointed_at)
        return _build_choices_tokens(
            items,
            indices,
            pointed_at,
            pointer,
            highlight_pointed_item=highlight_pointed_item,
        )

    def move_pointed_at(delta: int) -> None:
        nonlocal pointed_at
        indices, _ = _filter_items(items, get_filter_text())
        if not indices:
            return

        pointed_at = _coerce_pointed_at_to_selectable(items, indices, pointed_at)
        for _ in range(len(indices)):
            pointed_at = (pointed_at + delta) % len(indices)
            idx = indices[pointed_at]
            if items[idx].selectable:
                return

    def on_search_changed(_buf: Buffer) -> None:
        nonlocal pointed_at
        pointed_at = 0
        with contextlib.suppress(Exception):
            get_app().invalidate()

    kb = KeyBindings()

    @kb.add(Keys.ControlC, eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    @kb.add(Keys.ControlQ, eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    @kb.add(Keys.Down, eager=True)
    def _(event: KeyPressEvent) -> None:
        move_pointed_at(+1)
        event.app.invalidate()

    @kb.add(Keys.Up, eager=True)
    def _(event: KeyPressEvent) -> None:
        move_pointed_at(-1)
        event.app.invalidate()

    @kb.add(Keys.Enter, eager=True)
    def _(event: KeyPressEvent) -> None:
        indices, _ = _filter_items(items, get_filter_text())
        if not indices:
            event.app.exit(result=None)
            return

        nonlocal pointed_at
        pointed_at = _coerce_pointed_at_to_selectable(items, indices, pointed_at)
        idx = indices[pointed_at % len(indices)]
        value = items[idx].value
        if value is None:
            event.app.exit(result=None)
            return
        event.app.exit(result=value)

    @kb.add(Keys.Tab, eager=True)
    def _(event: KeyPressEvent) -> None:
        """Accept the currently pointed item."""
        indices, _ = _filter_items(items, get_filter_text())
        if not indices:
            event.app.exit(result=None)
            return

        nonlocal pointed_at
        pointed_at = _coerce_pointed_at_to_selectable(items, indices, pointed_at)
        idx = indices[pointed_at % len(indices)]
        value = items[idx].value
        if value is None:
            event.app.exit(result=None)
            return
        event.app.exit(result=value)

    @kb.add(Keys.Escape, eager=True)
    def _(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        if use_search_filter and search_buffer is not None and search_buffer.text:
            search_buffer.reset(append_to_history=False)
            pointed_at = 0
            event.app.invalidate()
            return
        event.app.exit(result=None)

    if use_search_filter and search_buffer is not None:
        search_buffer.on_text_changed += on_search_changed

    if initial_value is not None:
        try:
            full_index = next(i for i, it in enumerate(items) if it.value == initial_value)
            indices, _ = _filter_items(items, get_filter_text())  # pyright: ignore[reportAssignmentType]
            pointed_at = indices.index(full_index) if full_index in indices else 0
        except StopIteration:
            pointed_at = 0

    header_window = Window(
        FormattedTextControl(get_header_tokens),
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
    spacer_window = Window(
        FormattedTextControl([("", "")]),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    list_window = Window(
        FormattedTextControl(get_choices_tokens),
        # Keep 1 line of context above the cursor so non-selectable header rows
        # (e.g. provider group labels) remain visible when wrapping back to the
        # first selectable item in a scrolled list.
        scroll_offsets=ScrollOffsets(top=1, bottom=2),
        allow_scroll_beyond_bottom=True,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )

    search_container: Container | None = None
    search_input_window: Window | None = None
    if use_search_filter and search_buffer is not None:
        search_input_window, search_container = _build_search_container(search_buffer, search_placeholder)

    base_style = Style(
        [
            ("frame.border", "fg:ansibrightblack dim"),
            ("frame.label", "fg:ansibrightblack italic"),
            ("search_prefix", "fg:ansibrightblack"),
            ("search_placeholder", "fg:ansibrightblack italic"),
        ]
    )
    merged_style = merge_styles([base_style, style] if style is not None else [base_style])

    root_children: list[Container] = [top_spacer_window, header_window, spacer_window, list_window]
    if search_container is not None:
        root_children.append(search_container)

    app: Application[T | None] = Application(
        layout=Layout(HSplit(root_children), focused_element=search_input_window or list_window),
        key_bindings=merge_key_bindings([load_key_bindings(), kb]),
        style=merged_style,
        mouse_support=False,
        full_screen=False,
        erase_when_done=True,
    )
    app.renderer.cpr_not_supported_callback = lambda: None
    return app.run()


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
    - Submit tab performs final submit/cancel
    """
    if not questions:
        return None
    if any(not question.items for question in questions):
        return None

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    submit_tab_idx = len(questions)
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

        active_tab_idx = (active_tab_idx + delta) % (len(questions) + 1)
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

        if input_text.strip() and question.other_value is not None and question.other_value not in values:
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
        for idx, question in enumerate(questions):
            tab_style = "class:question_tab_active" if idx == active_tab_idx else "class:question_tab_inactive"
            check = "☒" if answered_by_question[idx] else "☐"
            tokens.append((tab_style, f"{check} {question.header}"))
            tokens.append(("class:text", "   "))

        submit_style = "class:question_tab_active" if _is_submit_tab() else "class:question_tab_inactive"
        tokens.append((submit_style, "✔ Submit"))
        tokens.append(("class:meta", "  Tab to cycle · Enter to confirm"))
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

            if question.multi_select:
                marker = "[x] " if idx in selected_indices else "[ ] "
                tokens.append(("class:text", marker))

            title_tokens = _restyle_title(item.title, "class:highlighted") if is_pointed else item.title
            if idx == len(question.items) - 1:
                title_tokens = _trim_last_newline(title_tokens)
            tokens.extend(_indent_multiline_tokens(title_tokens, pointer_pad))

        return tokens

    def _build_submit_choices_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "

        for idx, question in enumerate(questions):
            tokens.append(("class:text", f" ● {question.message}\n"))
            tokens.append(("class:meta", f"   → {_answer_summary(idx)}\n"))

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
        row_num = f"{len(_current_question().items) + 1}. "
        if not _is_submit_tab() and _is_input_row(pointed_at_by_question[_current_question_idx()]):
            return [("class:pointer", pointed_prefix), ("class:text", row_num)]
        return [("class:text", pointer_pad + row_num)]

    def get_question_submit_tokens() -> list[tuple[str, str]]:
        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "
        question_idx = _current_question_idx()
        is_pointed = _is_question_submit_row(pointed_at_by_question[question_idx], question_idx=question_idx)
        if is_pointed:
            return [("class:pointer", pointed_prefix), ("class:submit_option", "✔ Submit")]
        return [("class:text", pointer_pad), ("class:submit_option", "✔ Submit")]

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
                _switch_tab(+1)
                _sync_focus(event.app)
                event.app.invalidate()
                return
            _toggle_current_option()
            event.app.invalidate()
            return

        _confirm_current_question()
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
    input_prefix_template = f" {pointer} {max_row_num}. "
    input_prefix_window = Window(
        FormattedTextControl(get_input_prefix_tokens),
        width=max(1, len(input_prefix_template)),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    other_label = "Other: "
    other_label_window = Window(
        FormattedTextControl([("class:text", other_label)]),
        width=len(other_label),
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
        [header_window, spacer_window, list_window, input_row_container, question_submit_row_container]
    )
    root = HSplit(root_children)

    def _before_render(app: Application[list[QuestionSelectResult[T]] | None]) -> None:
        _sync_focus(app)

    base_style = Style(
        [
            ("frame.border", "fg:ansibrightblack dim"),
            ("frame.label", "fg:ansibrightblack italic"),
            ("search_placeholder", "fg:ansibrightblack italic"),
            ("question_tab_inactive", "fg:ansibrightblack"),
            ("question_tab_active", "fg:ansigreen bg:ansibrightblack bold"),
            ("warning", "fg:ansiyellow"),
            ("submit_option", "fg:black bold"),
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
    input_placeholder: str = "Type something.",
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


# ---------------------------------------------------------------------------
# SelectOverlay: embedded overlay for existing prompt_toolkit Application
# ---------------------------------------------------------------------------


class SelectOverlay[T]:
    """Embedded single-choice selector overlay for an existing prompt_toolkit Application.

    Unlike `select_one()`, this does not create or run a new Application.
    It is designed for use inside an already-running PromptSession.app.
    """

    def __init__(
        self,
        *,
        pointer: str = "→",
        use_search_filter: bool = True,
        search_placeholder: str = "type to search",
        list_height: int = 8,
        highlight_pointed_item: bool = True,
        on_select: Callable[[T], Coroutine[Any, Any, None] | None] | None = None,
        on_cancel: Callable[[], Coroutine[Any, Any, None] | None] | None = None,
    ) -> None:
        self._pointer = pointer
        self._use_search_filter = use_search_filter
        self._search_placeholder = search_placeholder
        self._list_height = max(1, list_height)
        self._highlight_pointed_item = highlight_pointed_item
        self._on_select = on_select
        self._on_cancel = on_cancel

        self._is_open = False
        self._message: str = ""
        self._items: list[SelectItem[T]] = []
        self._pointed_at = 0

        self._prev_focus: Window | None = None
        self._search_buffer: Buffer | None = Buffer() if use_search_filter else None

        self._list_window: Window | None = None
        self._search_input_window: Window | None = None

        self.key_bindings = self._build_key_bindings()
        self.container = self._build_layout()

        if self._use_search_filter and self._search_buffer is not None:
            self._search_buffer.on_text_changed += self._on_search_changed

    def _get_filter_text(self) -> str:
        if self._use_search_filter and self._search_buffer is not None:
            return self._search_buffer.text
        return ""

    def _get_visible_indices(self) -> tuple[list[int], bool]:
        return _filter_items(self._items, self._get_filter_text())

    def _on_search_changed(self, _buf: Buffer) -> None:
        self._pointed_at = 0
        with contextlib.suppress(Exception):
            get_app().invalidate()

    def _build_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        is_open_filter = Condition(lambda: self._is_open)

        def move_pointed_at(delta: int) -> None:
            indices, _ = self._get_visible_indices()
            if not indices:
                return

            self._pointed_at = _coerce_pointed_at_to_selectable(self._items, indices, self._pointed_at)
            for _ in range(len(indices)):
                self._pointed_at = (self._pointed_at + delta) % len(indices)
                idx = indices[self._pointed_at]
                if self._items[idx].selectable:
                    return

        @kb.add(Keys.Down, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            move_pointed_at(+1)
            event.app.invalidate()

        @kb.add(Keys.Up, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            move_pointed_at(-1)
            event.app.invalidate()

        @kb.add(Keys.Enter, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            indices, _ = self._get_visible_indices()
            if not indices:
                self.close()
                return

            self._pointed_at = _coerce_pointed_at_to_selectable(self._items, indices, self._pointed_at)
            idx = indices[self._pointed_at % len(indices)]
            value = self._items[idx].value
            if value is None:
                self.close()
                return
            self.close()

            if self._on_select is None:
                return

            result = self._on_select(value)
            if hasattr(result, "__await__"):
                event.app.create_background_task(cast(Coroutine[Any, Any, None], result))

        @kb.add(Keys.Tab, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            indices, _ = self._get_visible_indices()
            if not indices:
                self.close()
                return

            self._pointed_at = _coerce_pointed_at_to_selectable(self._items, indices, self._pointed_at)
            idx = indices[self._pointed_at % len(indices)]
            value = self._items[idx].value
            if value is None:
                self.close()
                return
            self.close()

            if self._on_select is None:
                return

            result = self._on_select(value)
            if hasattr(result, "__await__"):
                event.app.create_background_task(cast(Coroutine[Any, Any, None], result))

        @kb.add(Keys.Escape, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            if self._use_search_filter and self._search_buffer is not None and self._search_buffer.text:
                self._search_buffer.reset(append_to_history=False)
                self._pointed_at = 0
                event.app.invalidate()
                return
            self._close_and_invoke_cancel(event)

        @kb.add(Keys.ControlL, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            self.close()
            event.app.invalidate()

        @kb.add(Keys.ControlC, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            self._close_and_invoke_cancel(event)

        return kb

    def _close_and_invoke_cancel(self, event: KeyPressEvent) -> None:
        self.close()
        if self._on_cancel is not None:
            result = self._on_cancel()
            if hasattr(result, "__await__"):
                event.app.create_background_task(cast(Coroutine[Any, Any, None], result))

    def _build_layout(self) -> ConditionalContainer:
        def get_header_tokens() -> list[tuple[str, str]]:
            return [("class:question", self._message + " ")]

        def get_choices_tokens() -> list[tuple[str, str]]:
            indices, _ = self._get_visible_indices()
            if indices:
                self._pointed_at = _coerce_pointed_at_to_selectable(self._items, indices, self._pointed_at)
            return _build_choices_tokens(
                self._items,
                indices,
                self._pointed_at,
                self._pointer,
                highlight_pointed_item=self._highlight_pointed_item,
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

        def get_list_height() -> int:
            # Dynamic height: min of configured height and available terminal space
            # Overhead: header(1) + spacer(1) + search(1) + frame borders(2) + prompt area(3)
            overhead = 8
            try:
                terminal_height = get_app().output.get_size().rows
                available = max(3, terminal_height - overhead)
                cap = min(self._list_height, available)
            except Exception:
                cap = self._list_height

            # Shrink list height when content is shorter than the configured cap.
            # This is especially helpful for small pickers (e.g. thinking level)
            # where a fixed list_height would otherwise render extra blank rows.
            indices, _ = self._get_visible_indices()
            if not indices:
                return max(1, cap)

            visible_lines = 0
            for idx in indices:
                item = self._items[idx]
                newlines = sum(text.count("\n") for _style, text in item.title)
                visible_lines += max(1, newlines)
                if visible_lines >= cap:
                    break

            return max(1, min(cap, visible_lines))

        list_window = Window(
            FormattedTextControl(get_choices_tokens),
            height=get_list_height,
            # See select_one(): keep header rows visible when wrapping.
            # For embedded overlays, avoid reserving extra blank lines near the
            # bottom when the list height is tight (e.g. short pickers).
            scroll_offsets=ScrollOffsets(top=1, bottom=0),
            allow_scroll_beyond_bottom=False,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        )
        self._list_window = list_window

        search_container: Container | None = None
        if self._use_search_filter and self._search_buffer is not None:
            self._search_input_window, search_container = _build_search_container(
                self._search_buffer,
                self._search_placeholder,
                frame=False,
            )

        root_children: list[Container] = [header_window, spacer_window, list_window]
        if search_container is not None:
            root_children.append(search_container)

        framed_content = _build_rounded_frame(HSplit(root_children, padding=0), padding_x=1)
        return ConditionalContainer(content=framed_content, filter=Condition(lambda: self._is_open))

    @property
    def is_open(self) -> bool:
        return self._is_open

    def set_content(self, *, message: str, items: list[SelectItem[T]], initial_value: T | None = None) -> None:
        self._message = message
        self._items = items

        self._pointed_at = 0
        if initial_value is not None:
            try:
                full_index = next(i for i, it in enumerate(items) if it.value == initial_value)
                self._pointed_at = full_index
            except StopIteration:
                self._pointed_at = 0

        if self._use_search_filter and self._search_buffer is not None:
            self._search_buffer.reset(append_to_history=False)

    def open(self) -> None:
        if self._is_open:
            return
        self._is_open = True
        app = get_app()
        self._prev_focus = cast(Window | None, getattr(app.layout, "current_window", None))
        with contextlib.suppress(Exception):
            if self._search_input_window is not None:
                app.layout.focus(self._search_input_window)
            elif self._list_window is not None:
                app.layout.focus(self._list_window)
        app.invalidate()

    def close(self) -> None:
        if not self._is_open:
            return
        self._is_open = False
        app = get_app()
        prev = self._prev_focus
        self._prev_focus = None
        if prev is not None:
            with contextlib.suppress(Exception):
                app.layout.focus(prev)
        app.invalidate()
