from __future__ import annotations

import datetime
import shutil
from functools import cache
from importlib.resources import files
from pathlib import Path

from klaude_code.const import ProjectPaths, find_git_repo_root, project_key_from_path
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

PARALLEL_TOOL_CALLS_INST = """- Parallelize independent tool calls in a single message whenever possible."""

STOPPING_CONDITION_INST = (
    "- After each tool result, ask: can I now correctly answer the user's core request with the evidence in hand? "
    "If yes, stop calling tools and answer. Persistence means finishing the task, not maximizing tool loops."
)

BASH_SPECIALIZED_TOOL_INST = """- Use specialized file tools for reads/edits instead of Bash fallbacks."""
BASH_RG_SEARCH_INST = """- For file and text search in Bash, prefer `rg` and `rg --files`."""
BASH_NO_PYTHON_IO_INST = """- Do not use Python for simple file read/write operations."""
BASH_NO_CHAINED_SEPARATORS_INST = (
    """- Do not chain unrelated bash commands with separator prints like `echo "===";` -- the merged output renders poorly. Run them as separate calls (in parallel when independent)."""
)
BASH_GIT_HISTORY_INST = (
    """- Use `git log` and `git blame` to search codebase history when additional context is required."""
)

READ_BEFORE_EDIT_INST = """- NEVER propose changes to or answer questions about code you haven't read. Investigate by reading relevant files before responding. If the user references a specific file, read it first -- do not speculate."""

PREFER_TOOL_OVER_SPECULATION_INST = (
    """- When information about the codebase is incomplete, prefer opening a file or running a tool over speculating."""
)

AGENT_FINDER_INST = (
    "- For broad codebase exploration, cross-directory tracing, concept-based searches, or when you "
    'would otherwise chain multiple search steps, use `Agent` with `type="finder"` instead of '
    "doing all searches yourself."
)
AGENT_FINDER_PARALLEL_INST = """- Launch multiple finder sub-agents in parallel when tasks are independent."""

TODO_FREQUENT_USAGE_INST = """- Use `TodoWrite` frequently for planning and tracking progress on multi-step tasks."""
TODO_COMPLETE_IMMEDIATELY_INST = """- Mark todos completed immediately when finished. Do not batch-complete later."""

ASK_USER_QUESTION_USAGE_INST = (
    """- Use the AskUserQuestion tool to ask questions, clarify and gather information as needed."""
)

EDIT_WRITE_PREFERENCE_INST = """- Prefer `edit` for existing files. Use `write` only for new files, or after reading an existing file and deciding to replace it end-to-end because most of it is changing."""
EDIT_PARALLELIZE_INST = """- Parallelize independent work when safe, such as reads, searches, checks, or disjoint `edit` calls, including disjoint sections of the same file."""
EDIT_VALIDATION_LOOP_INST = (
    "- After making changes, run the most relevant validation available: targeted unit tests for the changed behavior, "
    "type checks or linters when applicable, build checks for affected packages, or a minimal smoke command when full "
    "validation is too expensive. If validation cannot be run in this environment, say so and describe the next best check."
)

WRITE_CREATE_WHEN_NEEDED_INST = """- NEVER create files unless necessary for the task. Prefer editing existing files."""

WRITE_SMALL_PAYLOAD_INST = (
    "- Avoid writing an entire large file in one `Write` call. "
    "For existing files, prefer multiple targeted `Edit` calls over a single `Write` that replaces the whole file. "
    "When creating a new large file, split the work into an initial `Write` of the skeleton followed by `Edit` calls to fill in sections."
)

APPLY_PATCH_SMALL_PAYLOAD_INST = (
    "- Avoid giant patches. Split large multi-file patches into several smaller `apply_patch` calls "
    "rather than one massive patch. Each call should cover a small, cohesive set of changes."
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
        STOPPING_CONDITION_INST,
        PREFER_TOOL_OVER_SPECULATION_INST,
        EXTERNAL_REFS_INST,
    ]

    if tools.BASH in tool_name_set:
        strategy_lines.extend(
            [
                BASH_SPECIALIZED_TOOL_INST,
                BASH_RG_SEARCH_INST,
                BASH_NO_PYTHON_IO_INST,
                BASH_NO_CHAINED_SEPARATORS_INST,
                BASH_GIT_HISTORY_INST,
            ]
        )

    if tools.READ in tool_name_set and (
        tools.APPLY_PATCH in tool_name_set or tools.EDIT in tool_name_set or tools.WRITE in tool_name_set
    ):
        strategy_lines.append(READ_BEFORE_EDIT_INST)

    if tools.AGENT in tool_name_set:
        strategy_lines.extend(
            [
                AGENT_FINDER_INST,
                AGENT_FINDER_PARALLEL_INST,
            ]
        )

    if tools.TODO_WRITE in tool_name_set:
        strategy_lines.extend([TODO_FREQUENT_USAGE_INST, TODO_COMPLETE_IMMEDIATELY_INST])

    if tools.ASK_USER_QUESTION in tool_name_set:
        strategy_lines.append(ASK_USER_QUESTION_USAGE_INST)

    if tools.EDIT in tool_name_set and tools.WRITE in tool_name_set:
        strategy_lines.extend([EDIT_WRITE_PREFERENCE_INST, EDIT_PARALLELIZE_INST])

    if tools.EDIT in tool_name_set or tools.WRITE in tool_name_set or tools.APPLY_PATCH in tool_name_set:
        strategy_lines.append(EDIT_VALIDATION_LOOP_INST)

    if tools.WRITE in tool_name_set:
        strategy_lines.append(WRITE_CREATE_WHEN_NEEDED_INST)

    if tools.WRITE in tool_name_set:
        strategy_lines.append(WRITE_SMALL_PAYLOAD_INST)

    if tools.APPLY_PATCH in tool_name_set:
        strategy_lines.append(APPLY_PATCH_SMALL_PAYLOAD_INST)

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
    workspace_root = find_git_repo_root(work_dir=work_dir) or work_dir
    available_commands = _get_available_commands()

    env_lines: list[str] = [
        "",
        "",
        "# Environment",
        f"Working directory: {work_dir}",
        f"Workspace root: {workspace_root}",
    ]

    if available_commands:
        env_lines.append("Available bash commands:")
        for cmd in available_commands:
            env_lines.append(f"- {cmd}")

    return "\n".join(env_lines)


def _build_env_info(model_name: str, work_dir: Path) -> str:
    """Build environment info section with dynamic runtime values."""

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    git_root = find_git_repo_root(work_dir=work_dir)
    is_missing_dir = not work_dir.exists()
    is_empty_dir = not is_missing_dir and not any(work_dir.iterdir())

    available_commands = _get_available_commands()

    cwd_display = (
        f"{work_dir} (not found)" if is_missing_dir else f"{work_dir} (empty)" if is_empty_dir else str(work_dir)
    )
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
    extended_thinking_prompt = (
        "\n\n" + load_prompt_by_path("prompts/system/extended-thinking-prompt.md")
        if model_id.supports_adaptive_thinking(model_name)
        else ""
    )
    auto_memory_prompt = _build_auto_memory_prompt(work_dir)
    dynamic_prompt = auto_memory_prompt + _build_env_info(model_name, work_dir)

    return (
        base_prompt
        + git_hygiene_prompt
        + conventions_prompt
        + extended_thinking_prompt
        + f"\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}"
        + dynamic_prompt
    )
