import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


@lru_cache(maxsize=1)
def get_system_prompt(model_name: str) -> str:
    # Read md located in the same package directory
    return (
        files(__package__)
        .joinpath("prompt.md")
        .read_text(encoding="utf-8")
        .format(
            working_directory=str(Path.cwd()),
            date=datetime.datetime.now().strftime("%Y-%m-%d"),
            is_git_repo=(Path.cwd() / ".git").exists(),
            model_name=model_name,
        )
    )
