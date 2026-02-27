from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from klaude_code.config.config import Config

from klaude_code.core.prompts.system_prompt import load_system_prompt
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
from klaude_code.protocol.model_id import (
    is_gpt5_model,
)
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.session import Session

type Reminder = Callable[[Session], Awaitable[message.DeveloperMessage | None]]


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompts/tools/reminders."""

    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    reminders: list[Reminder]


MAIN_AGENT_COMMON_BASE_TOOLS: list[str] = [tools.BASH, tools.READ]
MAIN_AGENT_GPT5_DIFF_TOOLS: list[str] = [tools.APPLY_PATCH, tools.UPDATE_PLAN]
MAIN_AGENT_NON_GPT5_DIFF_TOOLS: list[str] = [tools.EDIT, tools.WRITE, tools.TODO_WRITE]
MAIN_AGENT_COMMON_TOOLS: list[str] = [
    tools.REWIND,
    tools.TASK,
    tools.WEB_FETCH,
    tools.WEB_SEARCH,
    tools.ASK_USER_QUESTION,
]


STRUCTURED_OUTPUT_PROMPT_FOR_SUB_AGENT = """\

# Structured Output
You have a `report_back` tool available. When you complete the task,\
you MUST call `report_back` with the structured result matching the required schema.\
Only the content passed to `report_back` will be returned to user.\
"""


def load_agent_tools(
    model_name: str,
    sub_agent_type: tools.SubAgentType | None = None,
    config: Config | None = None,
) -> list[llm_param.ToolSchema]:
    """Get tools for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent tools. Otherwise returns sub-agent tools.
        config: Config for optional tool decisions.
    """

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        return get_tool_schemas(list(profile.tool_set))

    # Main agent tools = common + model-specific diff + common
    model_diff_tools = MAIN_AGENT_GPT5_DIFF_TOOLS if is_gpt5_model(model_name) else MAIN_AGENT_NON_GPT5_DIFF_TOOLS
    tool_names: list[str] = [
        *MAIN_AGENT_COMMON_BASE_TOOLS,
        *model_diff_tools,
        *MAIN_AGENT_COMMON_TOOLS,
    ]

    del config

    return get_tool_schemas(tool_names)


def load_agent_reminders(
    model_name: str,
    sub_agent_type: str | None = None,
    available_tools: list[llm_param.ToolSchema] | None = None,
) -> list[Reminder]:
    """Get reminders for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent reminders. Otherwise returns sub-agent reminders.
        available_tools: Tools available to the active profile.
    """

    del model_name

    reminders: list[Reminder] = []
    tool_name_set = {tool_schema.name for tool_schema in (available_tools or [])}

    # Enable todo reminders only when TodoWrite is actually available.
    if sub_agent_type is None and tools.TODO_WRITE in tool_name_set:
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
        agent_tools = load_agent_tools(model_name, sub_agent_type, config=self._config)
        agent_system_prompt = load_system_prompt(model_name, sub_agent_type, available_tools=agent_tools)
        agent_reminders = load_agent_reminders(model_name, sub_agent_type, available_tools=agent_tools)

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
            system_prompt="You're an agent running in user's terminal",
            tools=get_tool_schemas([tools.BASH, tools.EDIT, tools.WRITE, tools.READ]),
            reminders=[],
        )
        if output_schema:
            return with_structured_output(profile, output_schema)
        return profile
