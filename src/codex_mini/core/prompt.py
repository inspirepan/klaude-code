from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def get_system_prompt() -> str:
    # Read md located in the same package directory
    return files(__package__).joinpath("prompt.md").read_text(encoding="utf-8")
