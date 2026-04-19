from __future__ import annotations

from dataclasses import dataclass

from klaude_code.protocol import tools
from klaude_code.protocol.models import TaskMetadata


@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False
    task_metadata: TaskMetadata | None = None


@dataclass(frozen=True)
class SubAgentProfile:
    """Metadata describing a sub agent and how it integrates with the system.

    This dataclass contains all the information needed to:
    1. Register the sub agent with the system
    2. Generate the tool schema for the main agent
    """

    # Identity - single name used for type, config_key, and prompt_key
    name: str  # e.g., "general-purpose", "finder"

    # Sub-agent run configuration
    prompt_file: str = ""  # Path relative to klaude_code package (e.g. "prompts/sub_agents/prompt-sub-agent-finder.md")
    tool_set: tuple[str, ...] = ()  # Tools available to this sub agent

    # Entry-point metadata for Agent tool (RunSubAgent)
    invoker_summary: str = ""  # Short description shown under Agent tool supported types

    # When True, use the main agent's full system prompt instead of prompt_file
    use_main_prompt: bool = False

    # Fork the parent agent's conversation history into the sub-agent session.
    # When True, the sub-agent inherits the full thread context from the parent.
    fork_context: bool = False

    # UI display
    active_form: str = ""  # Active form for spinner status (e.g., "Tasking", "Finding")


_PROFILES: dict[str, SubAgentProfile] = {}


def register_sub_agent(profile: SubAgentProfile) -> None:
    if profile.name in _PROFILES:
        raise ValueError(f"Duplicate sub agent profile: {profile.name}")
    _PROFILES[profile.name] = profile


def get_sub_agent_profile(sub_agent_type: tools.SubAgentType) -> SubAgentProfile:
    try:
        return _PROFILES[sub_agent_type]
    except KeyError as exc:
        raise KeyError(f"Unknown sub agent type: {sub_agent_type}") from exc


def iter_sub_agent_profiles() -> list[SubAgentProfile]:
    return list(_PROFILES.values())


def get_all_names() -> list[str]:
    return list(_PROFILES.keys())


def is_sub_agent_tool(tool_name: str) -> bool:
    from klaude_code.protocol import tools

    return tool_name == tools.AGENT


# Import sub-agent modules to trigger registration
from klaude_code.protocol.sub_agent import finder as finder  # noqa: E402
from klaude_code.protocol.sub_agent import general_purpose as general_purpose  # noqa: E402
from klaude_code.protocol.sub_agent import review as review  # noqa: E402
from klaude_code.protocol.sub_agent import simplifier as simplifier  # noqa: E402
