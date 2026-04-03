from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from klaude_code.config.config import Config

from klaude_code.agent.attachments import (
    Attachment,
    at_file_reader_attachment,
    file_changed_externally_attachment,
    image_attachment,
    last_path_memory_attachment,
    last_path_skill_attachment,
    memory_attachment,
    skill_attachment,
    todo_attachment,
)
from klaude_code.llm import LLMClientABC
from klaude_code.prompts.system_prompt import load_system_prompt
from klaude_code.protocol import llm_param, tools
from klaude_code.protocol.model_id import (
    is_gpt5_model,
)
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.tool.tool_registry import get_tool_schemas


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompts/tools/attachments."""

    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    attachments: list[Attachment]


MAIN_AGENT_COMMON_BASE_TOOLS: list[str] = [tools.BASH, tools.READ]
MAIN_AGENT_GPT5_DIFF_TOOLS: list[str] = [tools.APPLY_PATCH, tools.TODO_WRITE]
MAIN_AGENT_NON_GPT5_DIFF_TOOLS: list[str] = [tools.EDIT, tools.WRITE, tools.TODO_WRITE]
MAIN_AGENT_COMMON_TOOLS: list[str] = [
    tools.HANDOFF,
    tools.AGENT,
    tools.WEB_FETCH,
    tools.WEB_SEARCH,
    tools.ASK_USER_QUESTION,
]


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
        if profile.tool_set:
            return get_tool_schemas(list(profile.tool_set))
        # Empty tool_set means inherit main agent tools; fall through below

    # Main agent tools = common + model-specific diff + common
    model_diff_tools = MAIN_AGENT_GPT5_DIFF_TOOLS if is_gpt5_model(model_name) else MAIN_AGENT_NON_GPT5_DIFF_TOOLS
    tool_names: list[str] = [
        *MAIN_AGENT_COMMON_BASE_TOOLS,
        *model_diff_tools,
        *MAIN_AGENT_COMMON_TOOLS,
    ]

    del config

    return get_tool_schemas(tool_names)


def load_agent_attachments(
    model_name: str,
    sub_agent_type: str | None = None,
    available_tools: list[llm_param.ToolSchema] | None = None,
) -> list[Attachment]:
    """Get attachments for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent attachments. Otherwise returns sub-agent attachments.
        available_tools: Tools available to the active profile.
    """

    del model_name
    del sub_agent_type

    has_todo_tool = available_tools is not None and any(t.name == tools.TODO_WRITE for t in available_tools)

    attachments: list[Attachment] = [
        memory_attachment,
        at_file_reader_attachment,
        file_changed_externally_attachment,
        last_path_memory_attachment,
        last_path_skill_attachment,
        image_attachment,
        skill_attachment,
    ]
    if has_todo_tool:
        attachments.append(todo_attachment)
    return attachments


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        work_dir: Path,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompts/tool/attachment registries."""

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        work_dir: Path,
    ) -> AgentProfile:
        model_name = llm_client.model_name
        agent_tools = load_agent_tools(model_name, sub_agent_type, config=self._config)
        agent_system_prompt = load_system_prompt(
            model_name, sub_agent_type, available_tools=agent_tools, work_dir=work_dir
        )
        agent_attachments = load_agent_attachments(model_name, sub_agent_type, available_tools=agent_tools)

        return AgentProfile(
            llm_client=llm_client,
            system_prompt=agent_system_prompt,
            tools=agent_tools,
            attachments=agent_attachments,
        )


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, attachments, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        sub_agent_type: tools.SubAgentType | None = None,
        *,
        work_dir: Path,
    ) -> AgentProfile:
        del sub_agent_type, work_dir
        return AgentProfile(
            llm_client=llm_client,
            system_prompt="You're an agent running in user's terminal",
            tools=get_tool_schemas([tools.BASH, tools.EDIT, tools.WRITE, tools.READ]),
            attachments=[],
        )
