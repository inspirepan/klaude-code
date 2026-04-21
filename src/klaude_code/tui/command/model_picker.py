"""Interactive model selection for CLI."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from klaude_code.config.loader import load_config
from klaude_code.config.model_matcher import match_model_from_config
from klaude_code.log import log


class ModelSelectStatus(Enum):
    SELECTED = "selected"
    CANCELLED = "cancelled"
    NO_MATCH = "no_match"
    NO_MODELS = "no_models"
    NON_TTY = "non_tty"
    ERROR = "error"


@dataclass
class ModelSelectResult:
    status: ModelSelectStatus
    model: str | None = None


def select_model_interactive(
    keywords: list[str] | None = None,
    initial_search_text: str | None = None,
) -> ModelSelectResult:
    """Interactive single-choice model selector.

    This function combines matching logic with interactive UI selection.
    For CLI usage.

    If keywords is provided, the model list is pre-filtered by model_id.

    If initial_search_text is provided, the full model list is shown with the search input pre-filled.
    """
    if initial_search_text is not None:
        initial_search_text = initial_search_text.strip() or None

    config = load_config()

    # Fast path: if the prefill uniquely matches a configured model, skip the picker.
    if initial_search_text and not keywords:
        prefill_match = match_model_from_config(initial_search_text)
        if prefill_match.matched_model:
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=prefill_match.matched_model)

    result = match_model_from_config(None)

    if result.error_message:
        return ModelSelectResult(status=ModelSelectStatus.NO_MODELS)

    if result.matched_model:
        return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=result.matched_model)

    if keywords:
        keywords_lower = [k.lower() for k in keywords]
        result.filtered_models = [
            m for m in result.filtered_models if any(kw in (m.model_id or "").lower() for kw in keywords_lower)
        ]
        result.filter_hint = ", ".join(keywords)
        result.matched_model = None

    if result.filter_hint and not result.filtered_models:
        log("(no match)")
        return ModelSelectResult(status=ModelSelectStatus.NO_MATCH)

    # Non-interactive environments (CI/pipes) should never enter an interactive prompt.
    # If we couldn't resolve to a single model deterministically above, fail with a clear hint.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        log(("Error: cannot use interactive model selection without a TTY", "red"))
        log(("Hint: pass --model <config-name> or set main_model in ~/.klaude/klaude-config.yaml", "yellow"))
        return ModelSelectResult(status=ModelSelectStatus.NON_TTY)

    # Interactive selection
    from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, build_model_select_items, select_one

    names = [m.selector for m in result.filtered_models]

    try:
        items = build_model_select_items(result.filtered_models)

        total_count = len(result.filtered_models)
        if result.filter_hint:
            message = f"Select a model ({total_count}, filtered by '{result.filter_hint}'):"
        else:
            message = f"Select a model ({total_count}):"

        initial_value = config.main_model
        if isinstance(initial_value, str) and initial_value and "@" not in initial_value:
            try:
                resolved = config.resolve_model_location_prefer_available(
                    initial_value
                ) or config.resolve_model_location(initial_value)
            except ValueError:
                resolved = None
            if resolved is not None:
                initial_value = f"{resolved[0]}@{resolved[1]}"

        selected = select_one(
            message=message,
            items=items,
            pointer="→",
            use_search_filter=True,
            initial_value=initial_value,
            initial_search_text=initial_search_text,
            style=DEFAULT_PICKER_STYLE,
        )
        if isinstance(selected, str) and selected in names:
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=selected)
    except KeyboardInterrupt:
        return ModelSelectResult(status=ModelSelectStatus.CANCELLED)
    except Exception as e:
        log((f"Failed to use prompt_toolkit for model selection: {e}", "yellow"))
        # Never return an unvalidated model name here.
        # If we can't interactively select, fall back to a known configured model.
        if result.matched_model and result.matched_model in names:
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=result.matched_model)
        if config.main_model and config.main_model in names:
            return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=config.main_model)
        if config.main_model and "@" not in config.main_model:
            try:
                resolved = config.resolve_model_location_prefer_available(
                    config.main_model
                ) or config.resolve_model_location(config.main_model)
            except ValueError:
                resolved = None
            if resolved is not None:
                selector = f"{resolved[0]}@{resolved[1]}"
                if selector in names:
                    return ModelSelectResult(status=ModelSelectStatus.SELECTED, model=selector)

    return ModelSelectResult(status=ModelSelectStatus.ERROR)
