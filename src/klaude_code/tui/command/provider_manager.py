"""Interactive provider state management."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Always
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.containers import ScrollOffsets
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output.color_depth import ColorDepth

from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.config.config import Config
from klaude_code.tui.input.pt_theme import get_default_picker_style


@dataclass(frozen=True, slots=True)
class ProviderState:
    name: str
    disabled: bool
    source: str
    model_count: int


def build_provider_states(config: Config) -> list[ProviderState]:
    """Build display states for all merged providers."""
    builtin_names = {provider.provider_name for provider in get_builtin_config().provider_list}
    return [
        ProviderState(
            name=provider.provider_name,
            disabled=provider.disabled,
            source="builtin" if provider.provider_name in builtin_names else "custom",
            model_count=len(provider.model_list),
        )
        for provider in config.provider_list
        if provider.provider_name not in builtin_names or not provider.is_api_key_missing()
    ]


def _list_height() -> Dimension:
    rows = shutil.get_terminal_size((80, 24)).lines
    return Dimension(max=max(6, rows - 8))


def manage_providers_interactive(states: list[ProviderState]) -> dict[str, bool] | None:
    """Manage provider states and return disabled values when saved."""
    if not states or not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    pointed_at = 0
    disabled_by_name = {state.name: state.disabled for state in states}
    save_index = len(states)

    def get_header_tokens() -> list[tuple[str, str]]:
        return [
            ("class:question", "Manage providers\n"),
            ("class:meta", "Up/Down move  Space toggle  Enter on Save  s save  Esc cancel\n"),
        ]

    def get_list_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        name_width = max(len(state.name) for state in states)
        for index, state in enumerate(states):
            selected = index == pointed_at
            tokens.append(("class:pointer" if selected else "class:text", " -> " if selected else "    "))
            if selected:
                tokens.append(("[SetCursorPosition]", ""))

            disabled = disabled_by_name[state.name]
            tokens.extend(
                [
                    (
                        "class:accent.red" if disabled else "class:accent.green",
                        "disabled  " if disabled else "enabled   ",
                    ),
                    ("class:highlighted" if selected else "class:msg", f"{state.name:<{name_width}}"),
                    ("class:meta", f"  {state.source}  {state.model_count} models"),
                    ("class:meta", "\n"),
                ]
            )

        selected = pointed_at == save_index
        tokens.extend(
            [
                ("class:meta", "\n"),
                ("class:pointer" if selected else "class:text", " -> " if selected else "    "),
            ]
        )
        if selected:
            tokens.append(("[SetCursorPosition]", ""))
        tokens.extend(
            [
                ("class:accent.green bold" if selected else "class:submit_option", "Save changes"),
                ("class:meta", "\n"),
            ]
        )
        return tokens

    def move(delta: int) -> None:
        nonlocal pointed_at
        pointed_at = min(max(pointed_at + delta, 0), save_index)

    def activate(event: KeyPressEvent) -> None:
        if pointed_at == save_index:
            event.app.exit(result=dict(disabled_by_name))
            return
        state = states[pointed_at]
        disabled_by_name[state.name] = not disabled_by_name[state.name]
        event.app.invalidate()

    kb = KeyBindings()

    @kb.add(Keys.Down, eager=True)
    def _(event: KeyPressEvent) -> None:
        move(1)
        event.app.invalidate()

    @kb.add(Keys.Up, eager=True)
    def _(event: KeyPressEvent) -> None:
        move(-1)
        event.app.invalidate()

    @kb.add(" ", eager=True)
    def _(event: KeyPressEvent) -> None:
        activate(event)

    @kb.add(Keys.Enter, eager=True)
    def _(event: KeyPressEvent) -> None:
        if pointed_at == save_index:
            activate(event)

    @kb.add("s", eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=dict(disabled_by_name))

    @kb.add(Keys.Escape, eager=True)
    @kb.add(Keys.ControlC, eager=True)
    @kb.add(Keys.ControlQ, eager=True)
    def _(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    header = Window(
        FormattedTextControl(get_header_tokens),
        height=2,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    provider_list = Window(
        FormattedTextControl(get_list_tokens),
        height=_list_height,
        scroll_offsets=ScrollOffsets(top=1, bottom=2),
        allow_scroll_beyond_bottom=True,
        dont_extend_height=Always(),
        always_hide_cursor=Always(),
    )
    app: Application[dict[str, bool] | None] = Application(
        layout=Layout(HSplit([Window(height=1), header, provider_list]), focused_element=provider_list),
        key_bindings=merge_key_bindings([load_key_bindings(), kb]),
        style=get_default_picker_style(),
        mouse_support=False,
        full_screen=False,
        erase_when_done=True,
        color_depth=ColorDepth.TRUE_COLOR,
    )
    app.renderer.cpr_not_supported_callback = lambda: None
    return app.run()
