from __future__ import annotations

import datetime
import shutil
from functools import cache
from importlib.resources import files
from pathlib import Path
from string import Template

from klaude_code.const import ProjectPaths, project_key_from_path
from klaude_code.protocol import llm_param, model_id, tools
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

AGENT_FINDER_INST = """- For broad codebase exploration, use `Agent` with `type="finder"`."""
AGENT_FINDER_PARALLEL_INST = """- Launch multiple finder sub-agents in parallel when tasks are independent."""
AGENT_REVIEW_INST = """- After completing complex or large-scale changes (touching 3+ files with non-trivial logic), launch an `Agent` with `type="review"` to review your work before reporting back to the user. Do NOT launch review for small, straightforward edits like config tweaks, single-file fixes, renames, or simple bug fixes."""
AGENT_REVIEW_FOLLOWUP_INST = """- For follow-up reviews (after fixing issues from a prior review), include the previous findings in the prompt and provide a diff command scoped to only the fix commits, so the reviewer can verify fixes incrementally instead of re-reviewing the entire changeset."""
AGENT_MEMORY_INST = """- After sessions with significant learnings (new commands, gotchas, architecture insights), launch an `Agent` with `type="memory"` to persist them into AGENTS.md files."""

TODO_FREQUENT_USAGE_INST = """- Use `TodoWrite` frequently for planning and tracking progress on multi-step tasks."""
TODO_COMPLETE_IMMEDIATELY_INST = """- Mark todos completed immediately when finished. Do not batch-complete later."""

ASK_USER_QUESTION_USAGE_INST = (
    """- Use the AskUserQuestion tool to ask questions, clarify and gather information as needed."""
)

EDIT_WRITE_PREFERENCE_INST = """- Prefer `edit` for existing files. Use `write` only for new files, or after reading an existing file and deciding to replace it end-to-end because most of it is changing."""
EDIT_PARALLELIZE_INST = """- Parallelize independent work when safe, such as reads, searches, checks, or disjoint `edit` calls, including disjoint sections of the same file."""

WRITE_CREATE_WHEN_NEEDED_INST = """- NEVER create files unless necessary for the task. Prefer editing existing files."""

EXTERNAL_REFS_INST = """- Pull in external references when uncertainty or risk is meaningful: unclear APIs/behavior, security-sensitive flows, migrations, performance-critical paths, or best-in-class patterns proven in open source or other language ecosystems. Prefer official docs first, then source."""


@cache
def load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache a prompt file path relative to core package."""

    return files("klaude_code.core").joinpath(prompt_path).read_text(encoding="utf-8").strip()


def load_main_base_prompt(model_name: str) -> str:
    """Load base prompt content for main agents.

    Routes to model-family-specific prompts when available.
    """

    if model_id.is_gpt5_model(model_name):
        return load_prompt_by_path("prompts/base-system-prompt-gpt.md")
    return load_prompt_by_path("prompts/base-system-prompt.md")


def build_dynamic_tool_strategy_prompt(available_tools: list[llm_param.ToolSchema]) -> str:
    """Build tool strategy guidance based on currently available tools."""

    tool_names = [tool_schema.name for tool_schema in available_tools]
    tool_name_set = set(tool_names)

    strategy_lines: list[str] = [PARALLEL_TOOL_CALLS_INST, EXTERNAL_REFS_INST]

    if tools.BASH in tool_name_set:
        strategy_lines.extend(
            [BASH_SPECIALIZED_TOOL_INST, BASH_RG_SEARCH_INST, BASH_NO_PYTHON_IO_INST, BASH_GIT_HISTORY_INST]
        )

    if tools.READ in tool_name_set and (
        tools.APPLY_PATCH in tool_name_set or tools.EDIT in tool_name_set or tools.WRITE in tool_name_set
    ):
        strategy_lines.append(READ_BEFORE_EDIT_INST)

    if tools.AGENT in tool_name_set:
        strategy_lines.extend([
            AGENT_FINDER_INST,
            AGENT_FINDER_PARALLEL_INST,
            AGENT_REVIEW_INST,
            AGENT_REVIEW_FOLLOWUP_INST,
            AGENT_MEMORY_INST,
        ])

    if tools.TODO_WRITE in tool_name_set:
        strategy_lines.extend([TODO_FREQUENT_USAGE_INST, TODO_COMPLETE_IMMEDIATELY_INST])

    if tools.ASK_USER_QUESTION in tool_name_set:
        strategy_lines.append(ASK_USER_QUESTION_USAGE_INST)

    if tools.EDIT in tool_name_set and tools.WRITE in tool_name_set:
        strategy_lines.extend([EDIT_WRITE_PREFERENCE_INST, EDIT_PARALLELIZE_INST])

    if tools.WRITE in tool_name_set:
        strategy_lines.append(WRITE_CREATE_WHEN_NEEDED_INST)

    lines = ["", "", "# Using your tools"]
    lines.extend(strategy_lines)
    return "\n".join(lines)


def build_main_system_prompt(model_name: str, available_tools: list[llm_param.ToolSchema]) -> str:
    """Build main-agent system prompt from base prompt plus dynamic tool strategy."""

    base_prompt = load_main_base_prompt(model_name)
    return base_prompt + build_dynamic_tool_strategy_prompt(available_tools)


def _build_env_info(model_name: str, work_dir: Path) -> str:
    """Build environment info section with dynamic runtime values."""

    from klaude_code.core.memory import find_git_repo_root

    cwd = work_dir
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    git_root = find_git_repo_root(work_dir=cwd)
    is_missing_dir = not cwd.exists()
    is_empty_dir = not is_missing_dir and not any(cwd.iterdir())

    available_commands: list[str] = []
    for command, desc in COMMAND_DESCRIPTIONS.items():
        if shutil.which(command) is not None:
            available_commands.append(f"{command}: {desc}")

    cwd_display = f"{cwd} (not found)" if is_missing_dir else f"{cwd} (empty)" if is_empty_dir else str(cwd)
    git_repo_line = (
        f"Current directory is a git repo (root: {git_root})"
        if git_root is not None
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


def _build_auto_memory_prompt(work_dir: Path) -> str:
    """Build auto-memory prompt with the project-specific memory directory path."""
    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    memory_dir = str(paths.memory_dir)
    template = load_prompt_by_path("prompts/auto-memory-prompt.md")
    return "\n\n" + template.format(memory_dir=memory_dir)


def load_system_prompt(
    model_name: str,
    sub_agent_type: tools.SubAgentType | None = None,
    available_tools: list[llm_param.ToolSchema] | None = None,
    *,
    work_dir: Path,
) -> str:
    """Get system prompt content for the given model and sub-agent type."""

    effective_work_dir = work_dir

    # Sub-agents with their own dedicated prompt get a minimal system prompt
    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        if not profile.use_main_prompt:
            from klaude_code.core.memory import find_git_repo_root

            workspace_root = find_git_repo_root(work_dir=effective_work_dir) or effective_work_dir
            base_prompt = Template(load_prompt_by_path(profile.prompt_file)).safe_substitute(
                workingDirectory=effective_work_dir,
                workspaceRoot=workspace_root,
            )
            return base_prompt

    # Main agent prompt path (also used by sub-agents with use_main_prompt=True)
    from klaude_code.skill.manager import format_available_skills_for_system_prompt

    base_prompt = build_main_system_prompt(model_name, available_tools or [])
    git_hygiene_prompt = "\n\n" + load_prompt_by_path("prompts/git-workspace-hygiene-prompt.md")
    conventions_prompt = "\n\n" + load_prompt_by_path("prompts/following-conventions-prompt.md")
    extended_thinking_prompt = (
        "\n\n" + load_prompt_by_path("prompts/extended-thinking-prompt.md")
        if model_id.supports_adaptive_thinking(model_name)
        else ""
    )
    auto_memory_prompt = _build_auto_memory_prompt(effective_work_dir)
    skills_prompt = format_available_skills_for_system_prompt()

    return (
        base_prompt
        + git_hygiene_prompt
        + conventions_prompt
        + extended_thinking_prompt
        + auto_memory_prompt
        + skills_prompt
        + _build_env_info(model_name, effective_work_dir)
    )
