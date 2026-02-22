from __future__ import annotations

from functools import cache
from importlib.resources import files

from klaude_code.protocol import llm_param, tools

PARALLEL_TOOL_CALLS_INST = """- Parallelize independent tool calls in a single message whenever possible."""

BASH_SPECIALIZED_TOOL_INST = """- Use specialized file tools for reads/edits instead of Bash fallbacks."""
BASH_RG_SEARCH_INST = """- For file and text search in Bash, prefer `rg` and `rg --files`."""
BASH_NO_PYTHON_IO_INST = """- Do not use Python for simple file read/write operations."""
BASH_GIT_HISTORY_INST = """- Use `git log` and `git blame` to search codebase history when additional context is required."""

READ_BEFORE_EDIT_INST = """- NEVER propose changes to code you haven't read. Read a file before editing it."""

TASK_EXPLORE_INST = """- For broad codebase exploration, use `Task` with `type="explore"`."""
TASK_EXPLORE_PARALLEL_INST = """- Launch multiple explore sub-agents in parallel when tasks are independent."""

TODO_FREQUENT_USAGE_INST = """- Use `TodoWrite` frequently for planning and tracking progress on multi-step tasks."""
TODO_COMPLETE_IMMEDIATELY_INST = """- Mark todos completed immediately when finished. Do not batch-complete later."""

UPDATE_PLAN_USAGE_INST = """- Use `update_plan` for non-trivial tasks with meaningful, verifiable steps."""
UPDATE_PLAN_STATUS_INST = (
    """- Keep exactly one step `in_progress`, update status as work progresses, and mark completed promptly."""
)

WRITE_CREATE_WHEN_NEEDED_INST = """- NEVER create files unless necessary for the task. Prefer editing existing files."""


@cache
def load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache a prompt file path relative to core package."""

    return files("klaude_code.core").joinpath(prompt_path).read_text(encoding="utf-8").strip()


def load_main_base_prompt(model_name: str) -> str:
    """Load base prompt content for main agents.

    Main non-image models share a single simplified prompt.
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

    if tools.TASK in tool_name_set:
        strategy_lines.extend([TASK_EXPLORE_INST, TASK_EXPLORE_PARALLEL_INST])

    if tools.TODO_WRITE in tool_name_set:
        strategy_lines.extend([TODO_FREQUENT_USAGE_INST, TODO_COMPLETE_IMMEDIATELY_INST])

    if tools.UPDATE_PLAN in tool_name_set:
        strategy_lines.extend([UPDATE_PLAN_USAGE_INST, UPDATE_PLAN_STATUS_INST])

    if tools.WRITE in tool_name_set:
        strategy_lines.append(WRITE_CREATE_WHEN_NEEDED_INST)

    lines = ["", "", "## Tool Strategy"]
    lines.extend(strategy_lines)
    return "\n".join(lines)


def build_main_system_prompt(model_name: str, available_tools: list[llm_param.ToolSchema]) -> str:
    """Build main-agent system prompt from base prompt plus dynamic tool strategy."""

    base_prompt = load_main_base_prompt(model_name)
    return base_prompt + build_dynamic_tool_strategy_prompt(available_tools)
