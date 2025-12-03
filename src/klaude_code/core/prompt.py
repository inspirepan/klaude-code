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

# Mapping from logical prompt keys to resource file paths under the core/prompt directory.
PROMPT_FILES: dict[str, str] = {
    "main_gpt_5_1": "prompts/prompt-codex-gpt-5-1.md",
    "main_gpt_5_1_codex_max": "prompts/prompt-codex-gpt-5-1-codex-max.md",
    # "main": "prompts/prompt-claude-code.md",
    "main": "prompts/prompt-minimal.md",
    "main_gemini": "prompts/prompt-gemini.md",  # https://ai.google.dev/gemini-api/docs/prompting-strategies?hl=zh-cn#agentic-si-template
    # Sub-agent prompts keyed by their name
    "Task": "prompts/prompt-subagent.md",
    "Oracle": "prompts/prompt-subagent-oracle.md",
    "Explore": "prompts/prompt-subagent-explore.md",
    "WebFetchAgent": "prompts/prompt-subagent-webfetch.md",
}


@lru_cache(maxsize=None)
def _load_base_prompt(file_key: str) -> str:
    """Load and cache the base prompt content from file."""
    try:
        prompt_path = PROMPT_FILES[file_key]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt key: {file_key}") from exc

    return files(__package__).joinpath(prompt_path).read_text(encoding="utf-8").strip()


def _get_file_key(model_name: str, sub_agent_type: str | None) -> str:
    """Determine which prompt file to use based on model and agent type."""
    if sub_agent_type is not None:
        return sub_agent_type

    match model_name:
        case "gpt-5.1-codex-max":
            return "main_gpt_5_1_codex_max"
        case name if "gpt-5" in name:
            return "main_gpt_5_1"
        case name if "gemini" in name:
            return "main_gemini"
        case _:
            return "main"


def _build_env_info(model_name: str) -> str:
    """Build environment info section with dynamic runtime values."""
    cwd = Path.cwd()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    is_git_repo = (cwd / ".git").exists()

    available_tools: list[str] = []
    for command, desc in COMMAND_DESCRIPTIONS.items():
        if shutil.which(command) is not None:
            available_tools.append(f"{command}: {desc}")

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
        env_lines.append("Prefer to use the following CLI utilities:")
        for tool in available_tools:
            env_lines.append(f"- {tool}")

    env_lines.append("</env>")

    return "\n".join(env_lines)


def get_system_prompt(model_name: str, sub_agent_type: str | None = None) -> str:
    """Get system prompt content for the given model and sub-agent type."""
    file_key = _get_file_key(model_name, sub_agent_type)
    base_prompt = _load_base_prompt(file_key)

    if model_name == "gpt-5.1-codex-max":
        return base_prompt

    return base_prompt + _build_env_info(model_name)
