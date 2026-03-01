from __future__ import annotations

import datetime
import shutil
from functools import cache
from importlib.resources import files
from pathlib import Path

from klaude_code.const import ProjectPaths, project_key_from_cwd
from klaude_code.protocol import llm_param, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile

COMMAND_DESCRIPTIONS: dict[str, str] = {
    "rg": "ripgrep - fast text search",
    "fd": "simple and fast alternative to find",
    "tree": "directory listing as a tree",
    "sg": "ast-grep - AST-aware code search",
    "jq": "command-line JSON processor",
    "jj": "jujutsu - Git-compatible version control system",
}

PARALLEL_TOOL_CALLS_INST = """- Parallelize independent tool calls in a single message whenever possible."""

BASH_SPECIALIZED_TOOL_INST = """- Use specialized file tools for reads/edits instead of Bash fallbacks."""
BASH_RG_SEARCH_INST = """- For file and text search in Bash, prefer `rg` and `rg --files`."""
BASH_NO_PYTHON_IO_INST = """- Do not use Python for simple file read/write operations."""
BASH_GIT_HISTORY_INST = (
    """- Use `git log` and `git blame` to search codebase history when additional context is required."""
)

READ_BEFORE_EDIT_INST = """- NEVER propose changes to code you haven't read. Read a file before editing it."""

AGENT_EXPLORE_INST = """- For broad codebase exploration, use `Agent` with `type="explore"`."""
AGENT_EXPLORE_PARALLEL_INST = """- Launch multiple explore sub-agents in parallel when tasks are independent."""

TODO_FREQUENT_USAGE_INST = """- Use `TodoWrite` frequently for planning and tracking progress on multi-step tasks."""
TODO_COMPLETE_IMMEDIATELY_INST = """- Mark todos completed immediately when finished. Do not batch-complete later."""

UPDATE_PLAN_USAGE_INST = """- Use `update_plan` for non-trivial tasks with meaningful, verifiable steps."""
UPDATE_PLAN_STATUS_INST = (
    """- Keep exactly one step `in_progress`, update status as work progresses, and mark completed promptly."""
)

ASK_USER_QUESTION_USAGE_INST = (
    """- Use the AskUserQuestion tool to ask questions, clarify and gather information as needed."""
)

WRITE_CREATE_WHEN_NEEDED_INST = """- NEVER create files unless necessary for the task. Prefer editing existing files."""


@cache
def load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache a prompt file path relative to core package."""

    return files("klaude_code.core").joinpath(prompt_path).read_text(encoding="utf-8").strip()


def load_main_base_prompt(model_name: str) -> str:
    """Load base prompt content for main agents.

    Main models share a single simplified prompt.
    """

    del model_name
    return load_prompt_by_path("prompts/base-system-prompt.md")


def build_dynamic_tool_strategy_prompt(available_tools: list[llm_param.ToolSchema]) -> str:
    """Build tool strategy guidance based on currently available tools."""

    tool_names = [tool_schema.name for tool_schema in available_tools]
    tool_name_set = set(tool_names)

    strategy_lines: list[str] = [PARALLEL_TOOL_CALLS_INST]

    if tools.BASH in tool_name_set:
        strategy_lines.extend(
            [BASH_SPECIALIZED_TOOL_INST, BASH_RG_SEARCH_INST, BASH_NO_PYTHON_IO_INST, BASH_GIT_HISTORY_INST]
        )

    if tools.READ in tool_name_set and (
        tools.APPLY_PATCH in tool_name_set or tools.EDIT in tool_name_set or tools.WRITE in tool_name_set
    ):
        strategy_lines.append(READ_BEFORE_EDIT_INST)

    if tools.AGENT in tool_name_set:
        strategy_lines.extend([AGENT_EXPLORE_INST, AGENT_EXPLORE_PARALLEL_INST])

    if tools.TODO_WRITE in tool_name_set:
        strategy_lines.extend([TODO_FREQUENT_USAGE_INST, TODO_COMPLETE_IMMEDIATELY_INST])

    if tools.UPDATE_PLAN in tool_name_set:
        strategy_lines.extend([UPDATE_PLAN_USAGE_INST, UPDATE_PLAN_STATUS_INST])

    if tools.ASK_USER_QUESTION in tool_name_set:
        strategy_lines.append(ASK_USER_QUESTION_USAGE_INST)

    if tools.WRITE in tool_name_set:
        strategy_lines.append(WRITE_CREATE_WHEN_NEEDED_INST)

    lines = ["", "", "# Using your tools"]
    lines.extend(strategy_lines)
    return "\n".join(lines)


def build_main_system_prompt(model_name: str, available_tools: list[llm_param.ToolSchema]) -> str:
    """Build main-agent system prompt from base prompt plus dynamic tool strategy."""

    base_prompt = load_main_base_prompt(model_name)
    return base_prompt + build_dynamic_tool_strategy_prompt(available_tools)


def _build_env_info(model_name: str) -> str:
    """Build environment info section with dynamic runtime values."""

    cwd = Path.cwd()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    is_git_repo = (cwd / ".git").exists()
    is_empty_dir = not any(cwd.iterdir())

    available_commands: list[str] = []
    for command, desc in COMMAND_DESCRIPTIONS.items():
        if shutil.which(command) is not None:
            available_commands.append(f"{command}: {desc}")

    cwd_display = f"{cwd} (empty)" if is_empty_dir else str(cwd)
    git_repo_line = (
        "Current directory is a git repo"
        if is_git_repo
        else "Current directory is not a git repo (Exercise caution when modifying files; back up when necessary)"
    )

    env_lines: list[str] = [
        "",
        "",
        "# Enviroment",
        "Here is useful information about the environment you are running in:",
        "<env>",
        f"Working directory: {cwd_display}",
        f"Today's Date: {today}",
        git_repo_line,
        f"You are powered by the model: {model_name}",
    ]

    if available_commands:
        env_lines.append("Available bash commands (use with `Bash` tool):")
        for command in available_commands:
            env_lines.append(f"- {command}")

    env_lines.append("</env>")
    return "\n".join(env_lines)


def _build_auto_memory_prompt() -> str:
    """Build auto-memory prompt with the project-specific memory directory path."""
    paths = ProjectPaths(project_key=project_key_from_cwd())
    memory_dir = str(paths.memory_dir)
    template = load_prompt_by_path("prompts/auto-memory-prompt.md")
    return "\n\n" + template.format(memory_dir=memory_dir)


def load_system_prompt(
    model_name: str,
    sub_agent_type: tools.SubAgentType | None = None,
    available_tools: list[llm_param.ToolSchema] | None = None,
) -> str:
    """Get system prompt content for the given model and sub-agent type."""

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        base_prompt = load_prompt_by_path(profile.prompt_file)
    else:
        base_prompt = build_main_system_prompt(model_name, available_tools or [])

    auto_memory_prompt = ""
    skills_prompt = ""
    if sub_agent_type is None:
        from klaude_code.skill.manager import format_available_skills_for_system_prompt

        auto_memory_prompt = _build_auto_memory_prompt()
        skills_prompt = format_available_skills_for_system_prompt()

    return base_prompt + auto_memory_prompt + skills_prompt + _build_env_info(model_name)
