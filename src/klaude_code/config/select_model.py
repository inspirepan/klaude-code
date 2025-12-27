import sys

from klaude_code.config.config import ModelEntry, load_config, print_no_available_models_hint
from klaude_code.trace import log


def _normalize_model_key(value: str) -> str:
    """Normalize a model identifier for loose matching.

    This enables aliases like:
    - gpt52 -> gpt-5.2
    - gpt5.2 -> gpt-5.2

    Strategy: case-fold + keep only alphanumeric characters.
    """

    return "".join(ch for ch in value.casefold() if ch.isalnum())


def select_model_from_config(preferred: str | None = None) -> str | None:
    """
    Interactive single-choice model selector.
    for `--select-model`

    If preferred is provided:
    - Exact match: return immediately
    - Single partial match (case-insensitive): return immediately
    - Otherwise: fall through to interactive selection
    """
    config = load_config()

    # Only show models from providers with valid API keys
    models: list[ModelEntry] = sorted(
        config.iter_model_entries(only_available=True), key=lambda m: m.model_name.lower()
    )

    if not models:
        print_no_available_models_hint()
        return None

    names: list[str] = [m.model_name for m in models]

    # Try to match preferred model name
    filtered_models = models
    if preferred and preferred.strip():
        preferred = preferred.strip()
        # Exact match
        if preferred in names:
            return preferred

        preferred_lower = preferred.lower()
        # Case-insensitive exact match (model_name or model_params.model)
        exact_ci_matches = [
            m
            for m in models
            if preferred_lower == m.model_name.lower() or preferred_lower == (m.model_params.model or "").lower()
        ]
        if len(exact_ci_matches) == 1:
            return exact_ci_matches[0].model_name

        # Normalized matching (e.g. gpt52 == gpt-5.2, gpt52 in gpt-5.2-2025-...)
        preferred_norm = _normalize_model_key(preferred)
        normalized_matches: list[ModelEntry] = []
        if preferred_norm:
            normalized_matches = [
                m
                for m in models
                if preferred_norm == _normalize_model_key(m.model_name)
                or preferred_norm == _normalize_model_key(m.model_params.model or "")
            ]
            if len(normalized_matches) == 1:
                return normalized_matches[0].model_name

            if not normalized_matches and len(preferred_norm) >= 4:
                normalized_matches = [
                    m
                    for m in models
                    if preferred_norm in _normalize_model_key(m.model_name)
                    or preferred_norm in _normalize_model_key(m.model_params.model or "")
                ]
                if len(normalized_matches) == 1:
                    return normalized_matches[0].model_name

        # Partial match (case-insensitive) on model_name or model_params.model.
        # If normalized matching found candidates (even if multiple), prefer those as the filter set.
        matches = normalized_matches or [
            m
            for m in models
            if preferred_lower in m.model_name.lower() or preferred_lower in (m.model_params.model or "").lower()
        ]
        if len(matches) == 1:
            return matches[0].model_name
        if matches:
            # Multiple matches: filter the list for interactive selection
            filtered_models = matches
        else:
            # No matches: show all models without filter hint
            preferred = None
            log(("No matching models found. Showing all models.", "yellow"))

    # Non-interactive environments (CI/pipes) should never enter an interactive prompt.
    # If we couldn't resolve to a single model deterministically above, fail with a clear hint.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        log(("Error: cannot use interactive model selection without a TTY", "red"))
        log(("Hint: pass --model <config-name> or set main_model in ~/.klaude/klaude-config.yaml", "yellow"))
        if preferred:
            log((f"Hint: '{preferred}' did not resolve to a single configured model", "yellow"))
        return None

    try:
        from prompt_toolkit.styles import Style

        from klaude_code.ui.terminal.selector import SelectItem, select_one

        max_model_name_length = max(len(m.model_name) for m in filtered_models)

        def _thinking_info(m: ModelEntry) -> str:
            thinking = m.model_params.thinking
            if not thinking:
                return ""
            if thinking.reasoning_effort:
                return f"reasoning {thinking.reasoning_effort}"
            if thinking.budget_tokens:
                return f"thinking budget {thinking.budget_tokens}"
            return "thinking (configured)"

        items: list[SelectItem[str]] = []
        for m in filtered_models:
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
                ("class:msg", first_line_prefix),
                ("class:msg bold", model_id),
                ("class:meta", f"  {meta_str}\n"),
            ]
            search_text = f"{m.model_name} {model_id} {m.provider}"
            items.append(SelectItem(title=title, value=m.model_name, search_text=search_text))

        try:
            message = f"Select a model (filtered by '{preferred}'):" if preferred else "Select a model:"
            result = select_one(
                message=message,
                items=items,
                pointer="→",
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
            if isinstance(result, str) and result in names:
                return result
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
