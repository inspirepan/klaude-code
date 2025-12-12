from klaude_code.config.config import ModelConfig, load_config
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
    assert config is not None
    models: list[ModelConfig] = sorted(config.model_list, key=lambda m: m.model_name.lower())

    if not models:
        raise ValueError("No models configured. Please update your config.yaml")

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
        normalized_matches: list[ModelConfig] = []
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

    try:
        import questionary

        choices: list[questionary.Choice] = []

        max_model_name_length = max(len(m.model_name) for m in filtered_models)
        for m in filtered_models:
            star = "★ " if m.model_name == config.main_model else "  "
            title = f"{star}{m.model_name:<{max_model_name_length}}   →  {m.model_params.model or 'N/A'} @ {m.provider}"
            choices.append(questionary.Choice(title=title, value=m.model_name))

        try:
            message = f"Select a model (filtered by '{preferred}'):" if preferred else "Select a model:"
            result = questionary.select(
                message=message,
                choices=choices,
                pointer="→",
                instruction="↑↓ to move • Enter to select",
                use_jk_keys=False,
                use_search_filter=True,
                style=questionary.Style(
                    [
                        ("instruction", "ansibrightblack"),
                        ("pointer", "ansicyan"),
                        ("highlighted", "ansicyan"),
                        ("text", "ansibrightblack"),
                        # search filter colors at the bottom
                        ("search_success", "noinherit fg:ansigreen"),
                        ("search_none", "noinherit fg:ansired"),
                        ("question-mark", "fg:ansigreen"),
                    ]
                ),
            ).ask()
            if isinstance(result, str) and result in names:
                return result
        except KeyboardInterrupt:
            return None
    except Exception as e:
        log(f"Failed to use questionary, falling back to default model, {e}")
        return preferred
