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

from klaude_code.core.reminders import (
    at_file_reader_reminder,
    empty_todo_reminder,
    file_changed_externally_reminder,
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
from klaude_code.protocol.sub_agent import (
    AVAILABILITY_IMAGE_MODEL,
    get_sub_agent_profile,
    get_sub_agent_profile_by_tool,
    sub_agent_tool_names,
)
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


NANO_BANANA_SYSTEM_PROMPT_PATH = "prompts/prompt-nano-banana.md"


STRUCTURED_OUTPUT_PROMPT = """\

# Structured Output
You have a `report_back` tool available. When you complete the task,\
you MUST call `report_back` with the structured result matching the required schema.\
Only the content passed to `report_back` will be returned to user.\
"""


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
    model_name: str,
    protocol: llm_param.LLMClientProtocol,
    sub_agent_type: str | None = None,
) -> str:
    """Get system prompt content for the given model and sub-agent type."""

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        base_prompt = _load_prompt_by_path(profile.prompt_file)
    else:
        file_key = _get_file_key(model_name, protocol)
        base_prompt = _load_base_prompt(file_key)

    if protocol == llm_param.LLMClientProtocol.CODEX_OAUTH:
        # Do not append environment info or skills info for Codex protocol.
        return base_prompt

    skills_prompt = ""
    if sub_agent_type is None:
        # Skills are progressive-disclosure: keep only metadata in the system prompt.
        from klaude_code.skill.manager import format_available_skills_for_system_prompt

        skills_prompt = format_available_skills_for_system_prompt()

    return base_prompt + _build_env_info(model_name) + skills_prompt


def _check_availability_requirement(requirement: str | None, config: Config | None) -> bool:
    """Check if a sub-agent's availability requirement is met.

    Args:
        requirement: The availability requirement constant (e.g., AVAILABILITY_IMAGE_MODEL).
        config: The config to check against.

    Returns:
        True if the requirement is met or if there's no requirement.
    """
    if requirement is None or config is None:
        return True

    if requirement == AVAILABILITY_IMAGE_MODEL:
        return config.has_available_image_model()

    # Unknown requirement, assume available
    return True


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
        tool_names = [tools.BASH, tools.READ, tools.APPLY_PATCH, tools.UPDATE_PLAN]
    elif "gemini-3" in model_name:
        tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE]
    else:
        tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.TODO_WRITE]

    # Add sub-agent tools, filtering by availability requirements
    sub_agent_names = sub_agent_tool_names(enabled_only=True, model_name=model_name)
    for name in sub_agent_names:
        profile = get_sub_agent_profile_by_tool(name)
        if profile is not None and _check_availability_requirement(profile.availability_requirement, config):
            tool_names.append(name)

    tool_names.extend([tools.MERMAID])
    # tool_names.extend([tools.MEMORY])
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
            file_changed_externally_reminder,
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
        system_prompt=base_prompt + STRUCTURED_OUTPUT_PROMPT,
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
        profile = AgentProfile(
            llm_client=llm_client,
            system_prompt=load_system_prompt(model_name, llm_client.protocol, sub_agent_type),
            tools=load_agent_tools(model_name, sub_agent_type, config=self._config),
            reminders=load_agent_reminders(model_name, sub_agent_type),
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


class NanoBananaModelProfileProvider(ModelProfileProvider):
    """Provider for the Nano Banana image generation model.

    This mode uses a dedicated system prompt and strips all tools/reminders.
    """

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
            system_prompt=_load_prompt_by_path(NANO_BANANA_SYSTEM_PROMPT_PATH),
            tools=[],
            reminders=[],
        )
        if output_schema:
            return with_structured_output(profile, output_schema)
        return profile
