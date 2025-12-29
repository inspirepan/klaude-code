"""Interactive model selection for CLI."""

import sys

from klaude_code.config.config import load_config
from klaude_code.config.select_model import match_model_from_config
from klaude_code.trace import log


def select_model_interactive(preferred: str | None = None) -> str | None:
    """Interactive single-choice model selector.

    This function combines matching logic with interactive UI selection.
    For CLI usage.

    If preferred is provided:
    - Exact match: return immediately
    - Single partial match (case-insensitive): return immediately
    - Otherwise: fall through to interactive selection
    """
    result = match_model_from_config(preferred)

    if result.error_message:
        return None

    if result.matched_model:
        return result.matched_model

    # Non-interactive environments (CI/pipes) should never enter an interactive prompt.
    # If we couldn't resolve to a single model deterministically above, fail with a clear hint.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        log(("Error: cannot use interactive model selection without a TTY", "red"))
        log(("Hint: pass --model <config-name> or set main_model in ~/.klaude/klaude-config.yaml", "yellow"))
        if preferred:
            log((f"Hint: '{preferred}' did not resolve to a single configured model", "yellow"))
        return None

    # Interactive selection
    from prompt_toolkit.styles import Style

    from klaude_code.ui.terminal.selector import build_model_select_items, select_one

    config = load_config()
    names = [m.model_name for m in result.filtered_models]

    try:
        items = build_model_select_items(result.filtered_models)

        message = f"Select a model (filtered by '{result.filter_hint}'):" if result.filter_hint else "Select a model:"
        selected = select_one(
            message=message,
            items=items,
            pointer="->",
            use_search_filter=True,
            initial_value=config.main_model,
            style=Style(
                [
                    ("pointer", "ansigreen"),
                    ("highlighted", "ansigreen"),
                    ("msg", ""),
                    ("meta", "fg:ansibrightblack"),
                    ("text", "ansibrightblack"),
                    ("question", "bold"),
                    ("search_prefix", "ansibrightblack"),
                    # search filter colors at the bottom
                    ("search_success", "noinherit fg:ansigreen"),
                    ("search_none", "noinherit fg:ansired"),
                ]
            ),
        )
        if isinstance(selected, str) and selected in names:
            return selected
    except KeyboardInterrupt:
        return None
    except Exception as e:
        log((f"Failed to use prompt_toolkit for model selection: {e}", "yellow"))
        # Never return an unvalidated model name here.
        # If we can't interactively select, fall back to a known configured model.
        if isinstance(preferred, str) and preferred in names:
            return preferred
        if config.main_model and config.main_model in names:
            return config.main_model

    return None
