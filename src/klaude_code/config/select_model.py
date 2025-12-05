from klaude_code.config.config import load_config
from klaude_code.trace import log


def select_model_from_config(preferred: str | None = None) -> str | None:
    """
    Interactive single-choice model selector.
    for `--select-model`
    """
    config = load_config()
    assert config is not None
    models = sorted(config.model_list, key=lambda m: m.model_name.lower())

    if not models:
        raise ValueError("No models configured. Please update your config.yaml")

    names: list[str] = [m.model_name for m in models]

    try:
        import questionary

        choices: list[questionary.Choice] = []

        max_model_name_length = max(len(m.model_name) for m in models)
        for m in models:
            star = "★ " if m.model_name == config.main_model else "  "
            title = f"{star}{m.model_name:<{max_model_name_length}}   →  {m.model_params.model or 'N/A'} @ {m.provider}"
            choices.append(questionary.Choice(title=title, value=m.model_name))

        try:
            result = questionary.select(
                message="Select a model:",
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
