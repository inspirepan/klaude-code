from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from klaude_code.protocol import tools

if TYPE_CHECKING:
    from klaude_code.protocol import model

AvailabilityPredicate = Callable[[str], bool]
PromptBuilder = Callable[[dict[str, Any]], str]


@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False
    task_metadata: model.TaskMetadata | None = None


def _default_prompt_builder(args: dict[str, Any]) -> str:
    """Default prompt builder that just returns the 'prompt' field."""
    return args.get("prompt", "")


@dataclass(frozen=True)
class SubAgentProfile:
    """Metadata describing a sub agent and how it integrates with the system.

    This dataclass contains all the information needed to:
    1. Register the sub agent with the system
    2. Generate the tool schema for the main agent
    3. Build the prompt for the sub agent
    """

    # Identity - single name used for type, tool_name, config_key, and prompt_key
    name: str  # e.g., "Task", "Oracle", "Explore"

    # Tool schema
    description: str  # Tool description shown to the main agent
    parameters: dict[str, Any] = field(
        default_factory=lambda: dict[str, Any](), hash=False
    )  # JSON Schema for tool parameters

    # System prompt
    prompt_file: str = ""  # Resource file path relative to core package (e.g., "prompts/prompt-sub-agent.md")

    # Sub agent configuration
    tool_set: tuple[str, ...] = ()  # Tools available to this sub agent
    prompt_builder: PromptBuilder = _default_prompt_builder  # Builds the sub agent prompt from tool arguments

    # UI display
    active_form: str = ""  # Active form for spinner status (e.g., "Tasking", "Exploring")

    # Availability
    enabled_by_default: bool = True
    show_in_main_agent: bool = True
    target_model_filter: AvailabilityPredicate | None = None

    # Structured output support: specifies which parameter in the tool schema contains the output schema
    output_schema_arg: str | None = None

    def enabled_for_model(self, model_name: str | None) -> bool:
        if not self.enabled_by_default:
            return False
        if model_name is None or self.target_model_filter is None:
            return True
        return self.target_model_filter(model_name)


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


def iter_sub_agent_profiles(enabled_only: bool = False, model_name: str | None = None) -> list[SubAgentProfile]:
    profiles = list(_PROFILES.values())
    if not enabled_only:
        return profiles
    return [p for p in profiles if p.enabled_for_model(model_name)]


def get_sub_agent_profile_by_tool(tool_name: str) -> SubAgentProfile | None:
    return _PROFILES.get(tool_name)


def is_sub_agent_tool(tool_name: str) -> bool:
    return tool_name in _PROFILES


def sub_agent_tool_names(enabled_only: bool = False, model_name: str | None = None) -> list[str]:
    return [
        profile.name
        for profile in iter_sub_agent_profiles(enabled_only=enabled_only, model_name=model_name)
        if profile.show_in_main_agent
    ]


# Import sub-agent modules to trigger registration
from klaude_code.protocol.sub_agent import explore as explore  # noqa: E402
from klaude_code.protocol.sub_agent import oracle as oracle  # noqa: E402
from klaude_code.protocol.sub_agent import task as task  # noqa: E402
from klaude_code.protocol.sub_agent import web as web  # noqa: E402
