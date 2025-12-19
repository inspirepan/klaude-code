import datetime
import shutil
from functools import cache
from importlib.resources import files
from pathlib import Path

from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import get_sub_agent_profile

COMMAND_DESCRIPTIONS: dict[str, str] = {
    "rg": "ripgrep - fast text search",
    "fd": "simple and fast alternative to find",
    "tree": "directory listing as a tree",
    "sg": "ast-grep - AST-aware code search",
    "jj": "jujutsu - Git-compatible version control system",
}

# Mapping from logical prompt keys to resource file paths under the core/prompt directory.
PROMPT_FILES: dict[str, str] = {
    "main_codex": "prompts/prompt-codex.md",
    "main_gpt_5_1_codex_max": "prompts/prompt-codex-gpt-5-1-codex-max.md",
    "main_gpt_5_2_codex": "prompts/prompt-codex-gpt-5-2-codex.md",
    "main": "prompts/prompt-claude-code.md",
    "main_gemini": "prompts/prompt-gemini.md",  # https://ai.google.dev/gemini-api/docs/prompting-strategies?hl=zh-cn#agentic-si-template
}


@cache
def _load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache prompt content from a file path relative to core package."""
    return files(__package__).joinpath(prompt_path).read_text(encoding="utf-8").strip()


def _load_base_prompt(file_key: str) -> str:
    """Load and cache the base prompt content from file."""
    try:
        prompt_path = PROMPT_FILES[file_key]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt key: {file_key}") from exc

    return _load_prompt_by_path(prompt_path)


def _get_file_key(model_name: str, protocol: llm_param.LLMClientProtocol) -> str:
    """Determine which prompt file to use based on model."""
    match model_name:
        case name if "gpt-5.2-codex" in name:
            return "main_gpt_5_2_codex"
        case name if "gpt-5.1-codex-max" in name:
            return "main_gpt_5_1_codex_max"
        case name if "gpt-5" in name:
            return "main_codex"
        case name if "gemini" in name:
            return "main_gemini"
        case _:
            return "main"


def _build_env_info(model_name: str) -> str:
    """Build environment info section with dynamic runtime values."""
    cwd = Path.cwd()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    is_git_repo = (cwd / ".git").exists()
    is_empty_dir = not any(cwd.iterdir())

    available_tools: list[str] = []
    for command, desc in COMMAND_DESCRIPTIONS.items():
        if shutil.which(command) is not None:
            available_tools.append(f"{command}: {desc}")

    cwd_display = f"{cwd} (empty)" if is_empty_dir else str(cwd)
    env_lines: list[str] = [
        "",
        "",
        "Here is useful information about the environment you are running in:",
        "<env>",
        f"Working directory: {cwd_display}",
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


def load_system_prompt(
    model_name: str, protocol: llm_param.LLMClientProtocol, sub_agent_type: str | None = None
) -> str:
    """Get system prompt content for the given model and sub-agent type."""
    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        base_prompt = _load_prompt_by_path(profile.prompt_file)
    else:
        file_key = _get_file_key(model_name, protocol)
        base_prompt = _load_base_prompt(file_key)

    if protocol == llm_param.LLMClientProtocol.CODEX:
        # Do not append environment info for Codex protocol
        return base_prompt

    return base_prompt + _build_env_info(model_name)
