"""Theme-aware prompt_toolkit styles derived from the rich palette.

This module mirrors the ``LIGHT_PALETTE``/``DARK_PALETTE`` colors defined in
``tui/components/rich/theme.py`` so that prompt_toolkit-powered UIs (REPL
input, selectors, question prompts) render in hex colors consistent with the
rest of the application.

The 24-bit color output is already forced at each ``Application``/``PromptSession``
construction site (see ``color_depth=ColorDepth.TRUE_COLOR``), so hex values
here are rendered exactly as specified.
"""

from __future__ import annotations

from prompt_toolkit.styles import Style

from klaude_code.tui.components.rich.theme import DARK_PALETTE, LIGHT_PALETTE, Palette

# Class tokens for per-fragment tuples. Defining them as constants keeps the
# call sites self-documenting and prevents typos.
CLASS_PROMPT = "class:prompt"
CLASS_PROMPT_BASH = "class:prompt.bash"
CLASS_META = "class:meta"
CLASS_MSG = "class:msg"
CLASS_TEXT = "class:text"
CLASS_SEPARATOR = "class:separator"
CLASS_SEPARATOR_HIGHLIGHTED = "class:separator.highlighted"
CLASS_ASSISTANT = "class:assistant"
CLASS_ACCENT_RED = "class:accent.red"
CLASS_ACCENT_GREEN = "class:accent.green"
CLASS_ACCENT_YELLOW = "class:accent.yellow"
CLASS_ACCENT_BLUE = "class:accent.blue"
CLASS_ACCENT_CYAN = "class:accent.cyan"
CLASS_ACCENT_MAGENTA = "class:accent.magenta"
CLASS_ACCENT_PURPLE = "class:accent.purple"
CLASS_ACCENT_ORANGE = "class:accent.orange"
CLASS_SKILL_PROJECT = "class:skill.project"
CLASS_SKILL_USER = "class:skill.user"
CLASS_SKILL_SYSTEM = "class:skill.system"


_theme_name: str = "dark"
_configured: bool = False


def configure_pt_theme(theme: str | None) -> None:
    """Configure the palette used by prompt_toolkit UIs.

    Pass ``"light"`` or ``"dark"``. Any other value (including ``None``)
    defaults to dark. Safe to call multiple times; the most recent setting
    wins.
    """

    global _theme_name, _configured
    _theme_name = "light" if theme == "light" else "dark"
    _configured = True


def _ensure_configured() -> None:
    """Lazy theme detection for CLI entry points that bypass ``run_interactive``.

    ``run_interactive`` calls :func:`configure_pt_theme` explicitly; the
    ``klaude --model`` / ``klaude --resume`` paths construct selectors
    before that runs, so we fall back to user config + terminal background
    detection on first use.
    """

    if _configured:
        return
    try:
        from klaude_code.config import load_config
        from klaude_code.tui.terminal.color import is_light_terminal_background

        theme = load_config().theme
        if theme is None:
            detected = is_light_terminal_background()
            if detected is True:
                theme = "light"
            elif detected is False:
                theme = "dark"
        configure_pt_theme(theme)
    except Exception:
        # Detection failure is non-fatal; fall back to dark palette.
        configure_pt_theme(None)


def _palette() -> Palette:
    _ensure_configured()
    return LIGHT_PALETTE if _theme_name == "light" else DARK_PALETTE


def _build_style_rules(palette: Palette) -> list[tuple[str, str]]:
    """Build prompt_toolkit style rules keyed by class name.

    Centralizing these rules lets every prompt_toolkit surface share the same
    palette derived from ``LIGHT_PALETTE``/``DARK_PALETTE``.
    """

    return [
        # --- Generic widget classes used across selectors / prompts -------
        ("pointer", f"fg:{palette.green}"),
        ("highlighted", f"fg:{palette.green}"),
        ("msg", ""),
        ("meta", f"fg:{palette.grey1}"),
        ("text", f"fg:{palette.grey2}"),
        ("question", "bold"),
        ("submit_option", "bold"),
        ("warning", f"fg:{palette.yellow}"),
        # --- Frame / preview ---------------------------------------------
        # Frame borders use grey3 so the chrome matches rich's
        # ``ThemeKey.LINES`` (welcome panel, trees) for a consistent
        # low-contrast structural color across both UIs.
        ("frame.border", f"fg:{palette.grey3}"),
        ("frame.label", f"italic fg:{palette.grey2}"),
        ("preview_border", f"fg:{palette.grey3}"),
        ("preview_content", ""),
        # --- Search filter -----------------------------------------------
        ("search_prefix", f"fg:{palette.grey1}"),
        ("search_placeholder", f"italic fg:{palette.grey1}"),
        ("search_input", ""),
        ("search_success", f"noinherit fg:{palette.green}"),
        ("search_none", f"noinherit fg:{palette.red}"),
        # --- Question tabs (ask_user_question) ---------------------------
        ("question_tab_inactive", f"reverse fg:{palette.grey1}"),
        ("question_tab_active", f"reverse bold fg:{palette.green}"),
        # --- REPL input --------------------------------------------------
        ("placeholder", f"italic fg:{palette.grey1}"),
        # Predicted-next-prompt suggestion: same dim color as the placeholder
        # but without italics so the user-facing hint reads as literal text.
        # Intentionally not using ``placeholder.suggestion`` because
        # prompt_toolkit cascades rules from the parent class (``placeholder``)
        # onto dotted child classes, which would re-introduce italics.
        ("prompt-suggestion", f"fg:{palette.grey1}"),
        ("placeholder-hint", f"fg:{palette.grey2}"),
        ("prompt", f"bold fg:{palette.magenta}"),
        ("prompt.bash", f"fg:{palette.green}"),
        # --- Completion menu --------------------------------------------
        ("completion-menu", "bg:default"),
        ("completion-menu.border", "bg:default"),
        ("completion-menu.completion", "bg:default fg:default"),
        ("completion-menu.meta.completion", f"bg:default fg:{palette.grey1}"),
        ("completion-menu.completion.current", f"noreverse bg:default fg:{palette.green}"),
        ("completion-menu.meta.completion.current", f"bg:default fg:{palette.green}"),
        ("scrollbar.background", "bg:default"),
        ("scrollbar.button", "bg:default"),
        # --- Fork / session selector decorations -------------------------
        ("separator", f"fg:{palette.grey2}"),
        ("separator.highlighted", f"fg:{palette.green}"),
        # Faintest structural line color, mirrors ``ThemeKey.LINES`` in the
        # rich theme (grey3). Used for low-contrast dividers such as the
        # provider-group separator in the model picker.
        ("lines", f"fg:{palette.grey3}"),
        ("assistant", f"fg:{palette.blue}"),
        # --- Skill completion badge colors -------------------------------
        ("skill.project", f"fg:{palette.magenta}"),
        ("skill.user", f"fg:{palette.blue}"),
        ("skill.system", f"fg:{palette.yellow}"),
        # --- Accent palette used by per-fragment tuples ------------------
        ("accent.red", f"fg:{palette.red}"),
        ("accent.green", f"fg:{palette.green}"),
        ("accent.yellow", f"fg:{palette.yellow}"),
        ("accent.blue", f"fg:{palette.blue}"),
        ("accent.cyan", f"fg:{palette.cyan}"),
        ("accent.magenta", f"fg:{palette.magenta}"),
        ("accent.purple", f"fg:{palette.purple}"),
        ("accent.orange", f"fg:{palette.orange}"),
        # --- Picker suggestion highlight --------------------------------
        # Applied to recommended rows (e.g. close matches when the current
        # main_model is invalid). The row keeps its regular fg; only the
        # background shifts to call attention without hiding other options.
        ("picker.suggested", f"bg:{palette.yellow_background}"),
        ("picker.suggested.badge", f"bold fg:{palette.yellow}"),
    ]


def get_base_style() -> Style:
    """Return the shared prompt_toolkit Style for the current theme."""

    return Style(_build_style_rules(_palette()))


def get_default_picker_style() -> Style:
    """Alias for ``get_base_style`` used by selector call sites.

    Kept as a separate name so callers that want to layer extra overrides on
    top (via ``merge_styles``) have a clearly-named base to start from.
    """

    return get_base_style()
