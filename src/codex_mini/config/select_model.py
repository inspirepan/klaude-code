from codex_mini.config.config import load_config
from codex_mini.trace import log_debug


def select_model_from_config(preferred: str | None = None) -> str | None:
    """
    Interactive single-choice model selector.
    for `--select-model`
    """
    config = load_config()
    models = sorted(config.model_list, key=lambda m: m.model_name.lower())

    if not models:
        raise ValueError("No models configured. Please update your config.yaml")

    names: list[str] = [m.model_name for m in models]
    default_name: str | None = (
        preferred if preferred in names else (config.main_model if config.main_model in names else None)
    )

    try:
        import questionary

        choices: list[questionary.Choice] = []

        max_model_name_length = max(len(m.model_name) for m in models)
        for m in models:
            star = "★ " if m.model_name == config.main_model else "  "
            label = [
                ("class:t", f"{star}{m.model_name:<{max_model_name_length}}   → "),
                ("class:b", m.model_params.model or "N/A"),
                ("class:d", f" {m.provider}"),
            ]
            choices.append(questionary.Choice(title=label, value=m.model_name))

        try:
            result = questionary.select(
                message="Select a model:",
                choices=choices,
                default=default_name,
                pointer="→",
                instruction="↑↓ to move • Enter to select",
                style=questionary.Style(
                    [
                        ("t", ""),
                        ("b", "bold"),
                        ("d", "dim"),
                    ]
                ),
            ).ask()
            if isinstance(result, str) and result in names:
                return result
        except KeyboardInterrupt:
            return None
    except Exception as e:
        log_debug(f"Failed to use questionary, falling back to default model, {e}")
        pass
