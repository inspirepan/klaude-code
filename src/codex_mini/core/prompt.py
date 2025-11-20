import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


@lru_cache(maxsize=None)
def get_system_prompt(model_name: str, key: str = "main") -> str:
    """Get system prompt content for the given model and prompt key."""

    if key == "main":
        prompt_path = "prompt_codex.md" if "gpt-5" in model_name else "prompt_claude_code.md"
    else:
        prompt_path = f"prompt_{key}.md"

    return (
        files(__package__)
        .joinpath(prompt_path)
        .read_text(encoding="utf-8")
        .format(
            working_directory=str(Path.cwd()),
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            is_git_repo=(Path.cwd() / ".git").exists(),
            model_name=model_name,
        )
    )
