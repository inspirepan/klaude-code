from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from functools import partial

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


def select_one[T](
    *,
    message: str,
    items: list[SelectItem[T]],
    pointer: str = "→",
    style: Style | None = None,
    use_search_filter: bool = True,
    initial_value: T | None = None,
    search_placeholder: str = "type to search",
) -> T | None:
    """Terminal single-choice selector based on prompt_toolkit.

    Features:
    - Search-as-you-type filter (optional)
    - Multi-line titles (via formatted text fragments)
    - Highlight entire pointed item via `class:highlighted`
    """

    if not items:
        return None

    # Non-interactive environments should not enter an interactive prompt.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    pointed_at = 0

    search_buffer: Buffer | None = None
    if use_search_filter:
        search_buffer = Buffer()

    def visible_indices() -> tuple[list[int], bool]:
        filter_text = search_buffer.text if (use_search_filter and search_buffer is not None) else ""
        if not filter_text:
            return list(range(len(items))), True

        needle = filter_text.lower()
        matched = [i for i, it in enumerate(items) if needle in it.search_text.lower()]
        if matched:
            return matched, True
        return list(range(len(items))), False

    def _restyle_title(title: list[tuple[str, str]], cls: str) -> list[tuple[str, str]]:
        # Keep simple text attributes like bold/italic while overriding colors via `cls`.
        keep_attrs = {"bold", "italic", "underline", "reverse", "blink", "strike"}
        restyled: list[tuple[str, str]] = []
        for old_style, text in title:
            attrs = [tok for tok in old_style.split() if tok in keep_attrs]
            style = f"{cls} {' '.join(attrs)}".strip()
            restyled.append((style, text))
        return restyled

    def get_header_tokens() -> list[tuple[str, str]]:
        return [("class:question", message + " ")]

    def get_choices_tokens() -> list[tuple[str, str]]:
        nonlocal pointed_at
        indices, _found = visible_indices()
        if not indices:
            return [("class:text", "(no items)\n")]

        pointed_at %= len(indices)
        tokens: list[tuple[str, str]] = []

        pointer_pad = " " * (2 + len(pointer))
        pointed_prefix = f" {pointer} "

        for pos, idx in enumerate(indices):
            is_pointed = pos == pointed_at

            if is_pointed:
                tokens.append(("class:pointer", pointed_prefix))
                tokens.append(("[SetCursorPosition]", ""))
            else:
                tokens.append(("class:text", pointer_pad))

            title_tokens = _restyle_title(items[idx].title, "class:highlighted") if is_pointed else items[idx].title
            tokens.extend(title_tokens)

        return tokens

    def _on_search_changed(_buf: Buffer) -> None:
        nonlocal pointed_at
        pointed_at = 0
        with contextlib.suppress(Exception):
            get_app().invalidate()

    kb = KeyBindings()

    @kb.add(Keys.ControlC, eager=True)
    @kb.add(Keys.ControlQ, eager=True)
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    _ = _cancel  # registered via decorator

    @kb.add(Keys.Down, eager=True)
    def _down(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        pointed_at += 1
        event.app.invalidate()

    _ = _down  # registered via decorator

    @kb.add(Keys.Up, eager=True)
    def _up(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        pointed_at -= 1
        event.app.invalidate()

    _ = _up  # registered via decorator

    @kb.add(Keys.Enter, eager=True)
    def _enter(event: KeyPressEvent) -> None:
        indices, _ = visible_indices()
        if not indices:
            event.app.exit(result=None)
            return
        idx = indices[pointed_at % len(indices)]
        event.app.exit(result=items[idx].value)

    _ = _enter  # registered via decorator

    @kb.add(Keys.Escape, eager=True)
    def _esc(event: KeyPressEvent) -> None:
        nonlocal pointed_at
        if use_search_filter and search_buffer is not None and search_buffer.text:
            search_buffer.reset(append_to_history=False)
            pointed_at = 0
            event.app.invalidate()
            return
        event.app.exit(result=None)

    _ = _esc  # registered via decorator

    if use_search_filter and search_buffer is not None:
        search_buffer.on_text_changed += _on_search_changed

    if initial_value is not None:
        try:
            full_index = next(i for i, it in enumerate(items) if it.value == initial_value)
            indices, _ = visible_indices()
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

    search_container = None
    search_input_window: Window | None = None
    if use_search_filter and search_buffer is not None:
        placeholder_text = f"{search_placeholder} · ↑↓ to select"

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
        search_input_window = input_window
        search_input_container = FloatContainer(
            content=input_window,
            floats=[Float(content=placeholder_window, top=0, left=0)],
        )

        def _rounded_frame(body: Container) -> HSplit:
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

        search_container = _rounded_frame(VSplit([search_prefix_window, search_input_container], padding=0))

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
