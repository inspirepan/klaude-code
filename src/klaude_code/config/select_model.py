from klaude_code.config.config import load_config
from klaude_code.trace import log


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
    models = sorted(config.model_list, key=lambda m: m.model_name.lower())

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
        # Partial match (case-insensitive) on model_name or model_params.model
        preferred_lower = preferred.lower()
        matches = [
            m
            for m in models
            if preferred_lower in m.model_name.lower() or preferred_lower in (m.model_params.model or "").lower()
        ]
        if len(matches) == 1:
            return matches[0].model_name
        if matches:
            # Multiple matches: filter the list for interactive selection
            filtered_models = matches

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
