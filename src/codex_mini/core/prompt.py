import datetime
import shutil
from functools import lru_cache
from importlib.resources import files
from pathlib import Path


COMMAND_DESCRIPTIONS: dict[str, str] = {
    "rg": "ripgrep - fast text search",
    "fd": "fd - simple and fast alternative to find",
    "tree": "tree - directory listing as a tree",
    "sg": "ast-grep - AST-aware code search",
}


@lru_cache(maxsize=None)
def get_system_prompt(model_name: str, key: str = "main") -> str:
    """Get system prompt content for the given model and prompt key."""

    cwd = Path.cwd()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    is_git_repo = (cwd / ".git").exists()

    available_tools: list[str] = []
    for command, desc in COMMAND_DESCRIPTIONS.items():
        if shutil.which(command) is not None:
            available_tools.append(f"{command}: {desc}")

    if key == "main":
        prompt_path = "prompt_codex.md" if "gpt-5" in model_name else "prompt_claude_code.md"
    else:
        prompt_path = f"prompt_{key}.md"

    base_prompt = (
        files(__package__)
        .joinpath(prompt_path)
        .read_text(encoding="utf-8")
        .format(
            working_directory=str(cwd),
            date=today,
            is_git_repo=is_git_repo,
            model_name=model_name,
        )
    )

    env_lines: list[str] = [
        "",
        "",
        "Here is useful information about the environment you are running in:",
        "<env>",
        f"Working directory: {cwd}",
        f"Today's Date: {today}",
        f"Is directory a git repo: {is_git_repo}",
        f"You are powered by the model: {model_name}",
    ]

    if available_tools:
        env_lines.append("Available CLI tools:")
        for tool in available_tools:
            env_lines.append(f"- {tool}")

    env_lines.append("</env>")

    env_info = "\n".join(env_lines)

    return base_prompt + env_info
