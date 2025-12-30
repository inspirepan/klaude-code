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


@dataclass(frozen=True, slots=True)
class SelectItem[T]:
    """One selectable item for terminal selection UI."""

    title: list[tuple[str, str]]
    value: T
    search_text: str


# ---------------------------------------------------------------------------
# Model selection items builder
# ---------------------------------------------------------------------------


def build_model_select_items(models: list[Any]) -> list[SelectItem[str]]:
    """Build SelectItem list from ModelEntry objects.

    Args:
        models: List of ModelEntry objects (from config.iter_model_entries).

    Returns:
        List of SelectItem[str] with model_name as the value.
    """
    if not models:
        return []

    max_model_name_length = max(len(m.model_name) for m in models)
    num_width = len(str(len(models)))

    def _thinking_info(m: Any) -> str:
        thinking = m.model_params.thinking
        if not thinking:
            return ""
        if thinking.reasoning_effort:
            return f"reasoning {thinking.reasoning_effort}"
        if thinking.budget_tokens:
            return f"thinking budget {thinking.budget_tokens}"
        return "thinking (configured)"

    items: list[SelectItem[str]] = []
    for idx, m in enumerate(models, 1):
        model_id = m.model_params.model or "N/A"
        first_line_prefix = f"{m.model_name:<{max_model_name_length}} → "
        thinking_info = _thinking_info(m)
        meta_parts: list[str] = [m.provider]
        if thinking_info:
            meta_parts.append(thinking_info)
        if m.model_params.verbosity:
            meta_parts.append(f"verbosity {m.model_params.verbosity}")
        meta_str = " · ".join(meta_parts)
        title = [
            ("class:meta", f"{idx:>{num_width}}. "),
            ("class:msg", first_line_prefix),
            ("class:msg bold", model_id),
            ("class:meta", f"  {meta_str}\n"),
        ]
        search_text = f"{m.model_name} {model_id} {m.provider}"
        items.append(SelectItem(title=title, value=m.model_name, search_text=search_text))

    return items


# ---------------------------------------------------------------------------
# Shared helpers for select_one() and SelectOverlay
# ---------------------------------------------------------------------------


def _restyle_title(title: list[tuple[str, str]], cls: str) -> list[tuple[str, str]]:
    """Re-apply a style class while keeping text attributes like bold/italic."""
    keep_attrs = {"bold", "italic", "underline", "reverse", "blink", "strike"}
    restyled: list[tuple[str, str]] = []
    for old_style, text in title:
        attrs = [tok for tok in old_style.split() if tok in keep_attrs]
        style = f"{cls} {' '.join(attrs)}".strip()
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


def _filter_items[T](
    items: list[SelectItem[T]],
    filter_text: str,
) -> tuple[list[int], bool]:
    """Return visible item indices and whether any matched the filter."""
    if not items:
        return [], True
    if not filter_text:
        return list(range(len(items))), True

    needle = filter_text.lower()
    matched = [i for i, it in enumerate(items) if needle in it.search_text.lower()]
    if matched:
        return matched, True
    return list(range(len(items))), False


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


def _build_rounded_frame(body: Container) -> HSplit:
    """Build a rounded border frame around the given container."""
    border = partial(Window, style="class:frame.border", height=1)
    top = VSplit(
        [
            border(width=1, char="╭"),
            border(char="─"),
            border(width=1, char="╮"),
        ],
        height=1,
        padding=0,
    )
    middle = VSplit(
        [
            border(width=1, char="│"),
            body,
            border(width=1, char="│"),
        ],
        padding=0,
    )
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
) -> tuple[Window, Container]:
    """Build the search input container with placeholder."""
    placeholder_text = f"{search_placeholder} · ↑↓ to select · esc to quit"

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
    framed = _build_rounded_frame(VSplit([search_prefix_window, search_input_container], padding=0))
    return input_window, framed


# ---------------------------------------------------------------------------
# select_one: standalone single-choice selector
# ---------------------------------------------------------------------------


def select_one[T](
    *,
    message: str,
    items: list[SelectItem[T]],
    pointer: str = "→",
    style: Style | None = None,
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
            pointed_at %= len(indices)
        return _build_choices_tokens(
            items,
            indices,
            pointed_at,
            pointer,
            highlight_pointed_item=highlight_pointed_item,
        )

    def on_search_changed(_buf: Buffer) -> None:
        nonlocal pointed_at
        pointed_at = 0
        with contextlib.suppress(Exception):
            get_app().invalidate()

    kb = KeyBindings()

    @kb.add(Keys.ControlC, eager=True)
    @kb.add(Keys.ControlQ, eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    @kb.add(Keys.Down, eager=True)
    def _(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        pointed_at += 1
        event.app.invalidate()

    @kb.add(Keys.Up, eager=True)
    def _(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        pointed_at -= 1
        event.app.invalidate()

    @kb.add(Keys.Enter, eager=True)
    def _(event: KeyPressEvent) -> None:
        indices, _ = _filter_items(items, get_filter_text())
        if not indices:
            event.app.exit(result=None)
            return
        idx = indices[pointed_at % len(indices)]
        event.app.exit(result=items[idx].value)

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
    spacer_window = Window(
        FormattedTextControl([("", "")]),
        height=1,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    list_window = Window(
        FormattedTextControl(get_choices_tokens),
        scroll_offsets=ScrollOffsets(top=0, bottom=2),
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
            ("frame.border", "fg:ansibrightblack"),
            ("frame.label", "fg:ansibrightblack italic"),
            ("search_prefix", "fg:ansibrightblack"),
            ("search_placeholder", "fg:ansibrightblack italic"),
        ]
    )
    merged_style = merge_styles([base_style, style] if style is not None else [base_style])

    root_children: list[Container] = [header_window, spacer_window, list_window]
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
    return app.run()


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

        @kb.add(Keys.Down, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            self._pointed_at += 1
            event.app.invalidate()

        @kb.add(Keys.Up, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            self._pointed_at -= 1
            event.app.invalidate()

        @kb.add(Keys.Enter, filter=is_open_filter, eager=True)
        def _(event: KeyPressEvent) -> None:
            indices, _ = self._get_visible_indices()
            if not indices:
                self.close()
                return
            idx = indices[self._pointed_at % len(indices)]
            value = self._items[idx].value
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
                self._pointed_at %= len(indices)
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
        list_window = Window(
            FormattedTextControl(get_choices_tokens),
            height=self._list_height,
            scroll_offsets=ScrollOffsets(top=0, bottom=2),
            allow_scroll_beyond_bottom=True,
            dont_extend_height=Always(),
            always_hide_cursor=Always(),
        )
        self._list_window = list_window

        search_container: Container | None = None
        if self._use_search_filter and self._search_buffer is not None:
            self._search_input_window, search_container = _build_search_container(
                self._search_buffer, self._search_placeholder
            )

        root_children: list[Container] = [header_window, spacer_window, list_window]
        if search_container is not None:
            root_children.append(search_container)

        return ConditionalContainer(
            content=HSplit(root_children, padding=0),
            filter=Condition(lambda: self._is_open),
        )

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
