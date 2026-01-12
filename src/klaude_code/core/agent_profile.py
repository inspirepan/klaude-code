from __future__ import annotations

import datetime
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from klaude_code.config.config import Config

from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.core.reminders import (
    at_file_reader_reminder,
    empty_todo_reminder,
    image_reminder,
    last_path_memory_reminder,
    memory_reminder,
    skill_reminder,
    todo_not_used_recently_reminder,
)
from klaude_code.core.tool.report_back_tool import ReportBackTool
from klaude_code.core.tool.tool_registry import get_tool_schemas
from klaude_code.llm import LLMClientABC
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.sub_agent import AVAILABILITY_IMAGE_MODEL, get_sub_agent_profile
from klaude_code.session import Session

type Reminder = Callable[[Session], Awaitable[message.DeveloperMessage | None]]


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompts/tools/reminders."""

    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    reminders: list[Reminder]


COMMAND_DESCRIPTIONS: dict[str, str] = {
    "rg": "ripgrep - fast text search",
    "fd": "simple and fast alternative to find",
    "tree": "directory listing as a tree",
    "sg": "ast-grep - AST-aware code search",
    "jq": "command-line JSON processor",
    "jj": "jujutsu - Git-compatible version control system",
}


# Prompt for antigravity protocol - used exactly as-is without any additions.
ANTIGRAVITY_PROMPT_PATH = "prompts/prompt-antigravity.md"


STRUCTURED_OUTPUT_PROMPT_FOR_SUB_AGENT = """\

# Structured Output
You have a `report_back` tool available. When you complete the task,\
you MUST call `report_back` with the structured result matching the required schema.\
Only the content passed to `report_back` will be returned to user.\
"""


@cache
def _load_prompt_by_path(prompt_path: str) -> str:
    """Load and cache prompt content from a file path relative to core package."""

    return files(__package__).joinpath(prompt_path).read_text(encoding="utf-8").strip()


def _load_prompt_by_model(model_name: str) -> str:
    """Load base prompt content based on model name."""

    match model_name:
        case name if "gpt-5.2-codex" in name:
            return _load_prompt_by_path("prompts/prompt-codex-gpt-5-2-codex.md")
        case name if "gpt-5.2" in name:
            return _load_prompt_by_path("prompts/prompt-codex-gpt-5-2.md")
        case name if "gpt-5" in name:
            return _load_prompt_by_path("prompts/prompt-codex.md")
        case name if "gemini" in name:
            return _load_prompt_by_path("prompts/prompt-gemini.md")
        case _:
            return _load_prompt_by_path("prompts/prompt-claude-code.md")


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
    model_name: str,
    protocol: llm_param.LLMClientProtocol,
    sub_agent_type: str | None = None,
    config: Config | None = None,
) -> str:
    """Get system prompt content for the given model and sub-agent type."""

    # For codex_oauth protocol, use dynamic prompts from GitHub (no additions).
    if protocol == llm_param.LLMClientProtocol.CODEX_OAUTH:
        from klaude_code.llm.openai_codex.prompt_sync import get_codex_instructions

        return get_codex_instructions(model_name)

    # For antigravity protocol, use exact prompt without any additions.
    if protocol == llm_param.LLMClientProtocol.ANTIGRAVITY:
        return _load_prompt_by_path(ANTIGRAVITY_PROMPT_PATH)

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        base_prompt = _load_prompt_by_path(profile.prompt_file)
    else:
        base_prompt = _load_prompt_by_model(model_name)

    skills_prompt = ""
    if sub_agent_type is None:
        # Skills are progressive-disclosure: keep only metadata in the system prompt.
        from klaude_code.skill.manager import format_available_skills_for_system_prompt

        skills_prompt = format_available_skills_for_system_prompt()

    return base_prompt + _build_env_info(model_name) + skills_prompt


def load_agent_tools(
    model_name: str,
    sub_agent_type: tools.SubAgentType | None = None,
    config: Config | None = None,
) -> list[llm_param.ToolSchema]:
    """Get tools for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent tools. Otherwise returns sub-agent tools.
        config: Config for checking sub-agent availability (e.g., image model availability).
    """

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        return get_tool_schemas(list(profile.tool_set))

    # Main agent tools
    if "gpt-5" in model_name:
        tool_names: list[str] = [tools.BASH, tools.READ, tools.APPLY_PATCH, tools.UPDATE_PLAN]
    else:
        tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.TODO_WRITE]

    tool_names.append(tools.TASK)
    if config is not None:
        helper = SubAgentModelHelper(config)
        if helper.check_availability_requirement(AVAILABILITY_IMAGE_MODEL):
            tool_names.append(tools.IMAGE_GEN)
    else:
        tool_names.append(tools.IMAGE_GEN)

    tool_names.append(tools.MERMAID)
    return get_tool_schemas(tool_names)


def load_agent_reminders(
    model_name: str,
    sub_agent_type: str | None = None,
) -> list[Reminder]:
    """Get reminders for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent reminders. Otherwise returns sub-agent reminders.
    """

    reminders: list[Reminder] = []

    # Only main agent (not sub-agent) gets todo reminders, and not for GPT-5
    if sub_agent_type is None and ("gpt-5" not in model_name and "gemini" not in model_name):
        reminders.append(empty_todo_reminder)
        reminders.append(todo_not_used_recently_reminder)

    reminders.extend(
        [
            memory_reminder,
            at_file_reader_reminder,
            last_path_memory_reminder,
            image_reminder,
            skill_reminder,
        ]
    )

    return reminders


def with_structured_output(profile: AgentProfile, output_schema: dict[str, Any]) -> AgentProfile:
    report_back_tool_class = ReportBackTool.for_schema(output_schema)
    base_prompt = profile.system_prompt or ""
    return AgentProfile(
        llm_client=profile.llm_client,
        system_prompt=base_prompt + STRUCTURED_OUTPUT_PROMPT_FOR_SUB_AGENT,
        tools=[*profile.tools, report_back_tool_class.schema()],
        reminders=profile.reminders,
    )


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompts/tool/reminder registries."""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentProfile:
        model_name = llm_client.model_name
        llm_config = llm_client.get_llm_config()

        # Image generation models should not have system prompt, tools, or reminders
        is_image_model = llm_config.modalities and "image" in llm_config.modalities
        if is_image_model:
            agent_system_prompt: str | None = None
            agent_tools: list[llm_param.ToolSchema] = []
            agent_reminders: list[Reminder] = [at_file_reader_reminder, image_reminder]
        else:
            agent_system_prompt = load_system_prompt(
                model_name, llm_client.protocol, sub_agent_type, config=self._config
            )
            agent_tools = load_agent_tools(model_name, sub_agent_type, config=self._config)
            agent_reminders = load_agent_reminders(model_name, sub_agent_type)

        profile = AgentProfile(
            llm_client=llm_client,
            system_prompt=agent_system_prompt,
            tools=agent_tools,
            reminders=agent_reminders,
        )
        if output_schema:
            return with_structured_output(profile, output_schema)
        return profile


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, reminders, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentProfile:
        del sub_agent_type
        profile = AgentProfile(
            llm_client=llm_client,
            system_prompt=None,
            tools=get_tool_schemas([tools.BASH, tools.EDIT, tools.WRITE, tools.READ]),
            reminders=[],
        )
        if output_schema:
            return with_structured_output(profile, output_schema)
        return profile
