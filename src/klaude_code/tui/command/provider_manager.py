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
from klaude_code.config.config import (
    Config,
    WebSearchConfig,
    WebSearchProviderConfig,
    WebSearchProviderName,
    resolve_api_key,
)
from klaude_code.tui.input.pt_theme import get_base_style


@dataclass(frozen=True, slots=True)
class ProviderState:
    name: str
    disabled: bool
    source: str
    model_count: int


@dataclass(frozen=True, slots=True)
class SearchProviderState:
    """Display state for one web search provider in the priority chain."""

    name: WebSearchProviderName
    enabled: bool
    has_api_key: bool
    model: str | None


@dataclass(frozen=True, slots=True)
class ManageProvidersResult:
    """Saved selection: LLM provider disabled flags + enabled search providers in priority order."""

    disabled_by_name: dict[str, bool]
    search_provider_names: list[WebSearchProviderName]


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


def build_search_provider_states(config: Config) -> list[SearchProviderState]:
    """Build display states for web search providers.

    Enabled entries come first in chain (priority) order; entries absent from
    the chain follow in builtin default order, marked disabled.
    """
    states = [
        SearchProviderState(
            name=entry.provider,
            enabled=True,
            has_api_key=resolve_api_key(entry.api_key) is not None,
            model=entry.model,
        )
        for entry in config.web_search.providers
    ]
    enabled_names = {state.name for state in states}
    for entry in get_builtin_config().web_search.providers:
        if entry.provider in enabled_names:
            continue
        states.append(
            SearchProviderState(
                name=entry.provider,
                enabled=False,
                has_api_key=resolve_api_key(entry.api_key) is not None,
                model=entry.model,
            )
        )
    return states


def build_web_search_config(config: Config, names: list[WebSearchProviderName]) -> WebSearchConfig:
    """Build a WebSearchConfig with ``names`` as the chain, preserving each entry's merged fields.

    Carrying the merged fields keeps YAML-level customizations (e.g. a custom
    model) intact when the user only reorders or toggles entries here.
    """
    merged_by_name = {entry.provider: entry for entry in config.web_search.providers}
    builtin_by_name = {entry.provider: entry for entry in get_builtin_config().web_search.providers}
    providers: list[WebSearchProviderConfig] = []
    for name in names:
        current = merged_by_name.get(name) or builtin_by_name.get(name)
        if current is None:
            continue
        providers.append(
            WebSearchProviderConfig(
                provider=current.provider,
                api_key=current.api_key,
                base_url=current.base_url,
                model=current.model,
            )
        )
    return WebSearchConfig(providers=providers)


def _list_height() -> Dimension:
    rows = shutil.get_terminal_size((80, 24)).lines
    return Dimension(max=max(6, rows - 8))


def manage_providers_interactive(
    states: list[ProviderState],
    search_states: list[SearchProviderState],
) -> ManageProvidersResult | None:
    """Manage LLM provider states and the web search chain; return the selection when saved."""
    if not states and not search_states:
        return None
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None

    pointed_at = 0
    disabled_by_name = {state.name: state.disabled for state in states}
    search_order = [state.name for state in search_states]
    search_enabled = {state.name: state.enabled for state in search_states}
    search_by_name = {state.name: state for state in search_states}
    llm_count = len(states)
    save_index = llm_count + len(search_order)

    def get_header_tokens() -> list[tuple[str, str]]:
        return [
            ("class:question", "Manage providers\n"),
            (
                "class:meta",
                "Up/Down move  Space toggle  Tab jump section  Alt+Up/Down reorder search  Enter on Save  s save  Esc cancel\n",
            ),
        ]

    def get_list_tokens() -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        if states:
            tokens.append(("class:meta bold", "  LLM providers\n"))
            name_width = max(len(state.name) for state in states)
            for index, state in enumerate(states):
                selected = index == pointed_at
                tokens.append(("class:pointer" if selected else "class:text", "  → " if selected else "    "))
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

        if search_order:
            tokens.append(("class:meta bold", "\n  Web search providers (priority order)\n"))
            search_name_width = max(len(name) for name in search_order)
            for offset, name in enumerate(search_order):
                index = llm_count + offset
                selected = index == pointed_at
                state = search_by_name[name]
                tokens.append(("class:pointer" if selected else "class:text", "  → " if selected else "    "))
                if selected:
                    tokens.append(("[SetCursorPosition]", ""))

                enabled = search_enabled[name]
                meta_parts = [state.model] if state.model else []
                if not state.has_api_key:
                    meta_parts.append("no API key")
                tokens.extend(
                    [
                        (
                            "class:accent.green" if enabled else "class:accent.red",
                            "enabled   " if enabled else "disabled  ",
                        ),
                        ("class:highlighted" if selected else "class:msg", f"{name:<{search_name_width}}"),
                        ("class:meta", f"  {'  '.join(meta_parts)}" if meta_parts else ""),
                        ("class:meta", "\n"),
                    ]
                )

        selected = pointed_at == save_index
        tokens.extend(
            [
                ("class:meta", "\n"),
                ("class:pointer" if selected else "class:text", "  → " if selected else "    "),
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
        pointed_at = (pointed_at + delta) % (save_index + 1)

    def save_result(app: Application[ManageProvidersResult | None]) -> None:
        app.exit(
            result=ManageProvidersResult(
                disabled_by_name=dict(disabled_by_name),
                search_provider_names=[name for name in search_order if search_enabled[name]],
            )
        )

    def activate(event: KeyPressEvent) -> None:
        if pointed_at == save_index:
            save_result(event.app)
            return
        if pointed_at < llm_count:
            state = states[pointed_at]
            disabled_by_name[state.name] = not disabled_by_name[state.name]
        else:
            name = search_order[pointed_at - llm_count]
            search_enabled[name] = not search_enabled[name]
        event.app.invalidate()

    def jump_section(delta: int) -> None:
        nonlocal pointed_at
        boundaries = [0, llm_count, save_index]
        current = 0
        for i, start in enumerate(boundaries):
            if pointed_at >= start:
                current = i
        pointed_at = boundaries[(current + delta) % len(boundaries)]

    def move_search_item(delta: int) -> bool:
        """Move the pointed search entry within the chain. Returns False outside the search zone."""
        nonlocal pointed_at
        if pointed_at < llm_count or pointed_at >= save_index:
            return False
        offset = pointed_at - llm_count
        target = offset + delta
        if target < 0 or target >= len(search_order):
            return True
        search_order[offset], search_order[target] = search_order[target], search_order[offset]
        pointed_at = llm_count + target
        return True

    kb = KeyBindings()

    @kb.add(Keys.Down, eager=True)
    def _(event: KeyPressEvent) -> None:
        move(1)
        event.app.invalidate()

    @kb.add(Keys.Up, eager=True)
    def _(event: KeyPressEvent) -> None:
        move(-1)
        event.app.invalidate()

    @kb.add(Keys.Tab, eager=True)
    def _(event: KeyPressEvent) -> None:
        jump_section(1)
        event.app.invalidate()

    @kb.add(Keys.BackTab, eager=True)
    def _(event: KeyPressEvent) -> None:
        jump_section(-1)
        event.app.invalidate()

    @kb.add("escape", "up", eager=True)
    def _(event: KeyPressEvent) -> None:
        if move_search_item(-1):
            event.app.invalidate()

    @kb.add("escape", "down", eager=True)
    def _(event: KeyPressEvent) -> None:
        if move_search_item(1):
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
        save_result(event.app)

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
    app: Application[ManageProvidersResult | None] = Application(
        layout=Layout(HSplit([Window(height=1), header, provider_list]), focused_element=provider_list),
        key_bindings=merge_key_bindings([load_key_bindings(), kb]),
        style=get_base_style(),
        mouse_support=False,
        full_screen=False,
        erase_when_done=True,
        color_depth=ColorDepth.TRUE_COLOR,
    )
    app.renderer.cpr_not_supported_callback = lambda: None
    return app.run()
