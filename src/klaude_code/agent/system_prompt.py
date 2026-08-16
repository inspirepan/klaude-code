from __future__ import annotations

import datetime
import shutil
from functools import cache
from importlib.resources import files
from pathlib import Path

from klaude_code.const import ProjectPaths, find_git_repo_root, find_jj_workspace_root, project_key_from_path
from klaude_code.protocol import llm_param, model_id, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.system_prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from klaude_code.protocol.system_prompt import (
    split_system_prompt_for_cache as _split_system_prompt_for_cache,
)
from klaude_code.protocol.system_prompt import (
    strip_system_prompt_boundary as _strip_system_prompt_boundary,
)

split_system_prompt_for_cache = _split_system_prompt_for_cache
strip_system_prompt_boundary = _strip_system_prompt_boundary

COMMAND_DESCRIPTIONS: dict[str, str] = {
    "rg": "ripgrep - fast text search",
    "fd": "simple and fast alternative to find",
    "tree": "directory listing as a tree",
    "sg": "ast-grep - AST-aware code search",
    "jq": "command-line JSON processor",
    "jj": "jujutsu - Git-compatible version control system",
}

#
# Guidance that belongs to a single tool lives in that tool's own description, not here.
# This section is only for cross-tool orchestration: which tool to reach for, and what to
# do after a tool returns.
#

PARALLEL_TOOL_CALLS_INST = """- Parallelize independent tool calls in a single message whenever possible."""

PREFER_TOOL_OVER_SPECULATION_INST = (
    "- Never propose changes to or answer questions about code you haven't read. When your information about "
    "the codebase is incomplete, open a file or run a tool instead of speculating."
)

BASH_SPECIALIZED_TOOL_INST = """- Use specialized file tools for reads/edits instead of Bash fallbacks."""

AGENT_FINDER_INST = (
    '- Delegate codebase searches to `Agent` with `type="finder"` by default: questions that span '
    "several files or directories, concept-based searches, or anything likely to take more than one "
    "search round. The finder reads through the noise and you keep only the conclusion in context. "
    "Search directly only for a single-step lookup where you already know the file, symbol, or exact "
    "string -- and if that first attempt misses, switch to finder instead of chaining more greps "
    "yourself. Once delegated, wait for the result; do not repeat the search."
)

EDIT_VALIDATION_LOOP_INST = (
    "- After making changes, run the most relevant validation available: targeted unit tests for the changed behavior, "
    "type checks or linters when applicable, build checks for affected packages, or a minimal smoke command when full "
    "validation is too expensive. If validation cannot be run in this environment, say so and describe the next best check."
)

REWIND_CHECKPOINT_INST = """- After each new user message, the system automatically injects a `<system-reminder>Checkpoint N</system-reminder>` marker into the conversation. These markers are rewind targets -- use the `Rewind` tool with a checkpoint ID to roll back conversation history to that point."""

EXTERNAL_REFS_INST = """- Pull in external references when uncertainty or risk is meaningful: unclear APIs/behavior, security-sensitive flows, migrations, performance-critical paths, or best-in-class patterns proven in open source or other language ecosystems. Prefer official docs first, then source."""


@cache
def load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache a prompt file path relative to klaude_code package."""

    return files("klaude_code").joinpath(prompt_path).read_text(encoding="utf-8").strip()


def load_main_base_prompt(model_name: str) -> str:
    """Load base prompt content for main agents.

    Routes to model-family-specific prompts when available.
    """

    if model_id.is_gpt5_model(model_name):
        return load_prompt_by_path("prompts/system/base-system-prompt-gpt.md")
    return load_prompt_by_path("prompts/system/base-system-prompt.md")


def build_dynamic_tool_strategy_prompt(available_tools: list[llm_param.ToolSchema]) -> str:
    """Build tool strategy guidance based on currently available tools."""

    tool_name_set = {tool_schema.name for tool_schema in available_tools}

    strategy_lines: list[str] = [
        PARALLEL_TOOL_CALLS_INST,
        PREFER_TOOL_OVER_SPECULATION_INST,
        EXTERNAL_REFS_INST,
    ]

    if tools.BASH in tool_name_set:
        strategy_lines.append(BASH_SPECIALIZED_TOOL_INST)

    if tools.AGENT in tool_name_set:
        strategy_lines.append(AGENT_FINDER_INST)

    if tools.EDIT in tool_name_set or tools.WRITE in tool_name_set or tools.APPLY_PATCH in tool_name_set:
        strategy_lines.append(EDIT_VALIDATION_LOOP_INST)

    if tools.REWIND in tool_name_set:
        strategy_lines.append(REWIND_CHECKPOINT_INST)

    lines = ["", "", "# Using your tools"]
    lines.extend(strategy_lines)
    return "\n".join(lines)


def build_main_system_prompt(model_name: str, available_tools: list[llm_param.ToolSchema]) -> str:
    """Build main-agent system prompt from base prompt plus dynamic tool strategy."""

    base_prompt = load_main_base_prompt(model_name)
    return base_prompt + build_dynamic_tool_strategy_prompt(available_tools)


def _get_available_commands() -> list[str]:
    """Return list of available bash commands with descriptions."""
    return [f"{cmd}: {desc}" for cmd, desc in COMMAND_DESCRIPTIONS.items() if shutil.which(cmd) is not None]


def build_sub_agent_env_info(work_dir: Path) -> str:
    """Build environment info block for sub-agents, appended at the end of their prompt."""
    workspace_root = find_jj_workspace_root(work_dir=work_dir) or find_git_repo_root(work_dir=work_dir) or work_dir
    available_commands = _get_available_commands()

    env_lines: list[str] = [
        "",
        "",
        "# Environment",
        f"Working directory: {work_dir}",
        f"Workspace root: {workspace_root}",
    ]

    if available_commands:
        env_lines.append("These are efficient bash commands installed in the current environment:")
        for cmd in available_commands:
            env_lines.append(f"- {cmd}")

    return "\n".join(env_lines)


def _build_env_info(model_name: str, work_dir: Path) -> str:
    """Build environment info section with dynamic runtime values."""

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    jj_root = find_jj_workspace_root(work_dir=work_dir)
    git_root = find_git_repo_root(work_dir=work_dir) if jj_root is None else None
    is_missing_dir = not work_dir.exists()
    is_empty_dir = not is_missing_dir and not any(work_dir.iterdir())

    available_commands = _get_available_commands()

    cwd_display = (
        f"{work_dir} (not found)" if is_missing_dir else f"{work_dir} (empty)" if is_empty_dir else str(work_dir)
    )
    repo_line = (
        f"Current directory is a jj repo (root: {jj_root})"
        if jj_root is not None
        else (
            f"Current directory is a git repo (root: {git_root})"
            if git_root is not None
            else "Current directory is not a jj or git repo (Exercise caution when modifying files; back up when necessary)"
        )
    )

    env_lines: list[str] = [
        "",
        "",
        "# Environment",
        "Here is useful information about the environment you are running in:",
        "<env>",
        f"Working directory: {cwd_display}",
        f"Today's Date: {today}",
        repo_line,
        f"You are powered by the model: {model_name}",
    ]

    if available_commands:
        env_lines.append(
            "These are efficient bash commands installed in the current environment (use with `Bash` tool):"
        )
        for command in available_commands:
            env_lines.append(f"- {command}")

    env_lines.append("</env>")
    return "\n".join(env_lines)


def _build_auto_memory_prompt(work_dir: Path) -> str:
    """Build auto-memory prompt with the project-specific memory directory path."""
    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    memory_dir = str(paths.memory_dir)
    template = load_prompt_by_path("prompts/system/auto-memory-prompt.md")
    return "\n\n" + template.format(memory_dir=memory_dir)


def load_system_prompt(
    model_name: str,
    sub_agent_type: tools.SubAgentType | None = None,
    available_tools: list[llm_param.ToolSchema] | None = None,
    *,
    work_dir: Path,
) -> str:
    """Get system prompt content for the given model and sub-agent type."""

    # Sub-agents with their own dedicated prompt get a minimal system prompt
    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        if not profile.use_main_prompt:
            base_prompt = load_prompt_by_path(profile.prompt_file)
            return base_prompt + build_sub_agent_env_info(work_dir)

    # Main agent prompt path (also used by sub-agents with use_main_prompt=True)
    base_prompt = build_main_system_prompt(model_name, available_tools or [])
    git_hygiene_prompt = "\n\n" + load_prompt_by_path("prompts/system/git-workspace-hygiene-prompt.md")
    conventions_prompt = "\n\n" + load_prompt_by_path("prompts/system/following-conventions-prompt.md")
    # auto_memory_prompt = _build_auto_memory_prompt(work_dir)
    dynamic_prompt = _build_env_info(model_name, work_dir)

    return (
        base_prompt + git_hygiene_prompt + conventions_prompt + f"\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}" + dynamic_prompt
    )
