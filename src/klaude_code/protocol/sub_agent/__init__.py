from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from klaude_code.protocol import tools

if TYPE_CHECKING:
    from klaude_code.protocol import model

PromptBuilder = Callable[[dict[str, Any]], str]

# Availability requirement constants
AVAILABILITY_IMAGE_MODEL = "image_model"


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

    # Identity - single name used for type, config_key, and prompt_key
    name: str  # e.g., "Task", "Explore", "Web", "ImageGen"

    # Sub-agent run configuration
    prompt_file: str = ""  # Resource file path relative to core package (e.g., "prompts/prompt-sub-agent.md")
    tool_set: tuple[str, ...] = ()  # Tools available to this sub agent
    prompt_builder: PromptBuilder = _default_prompt_builder  # Builds the sub agent prompt from tool arguments

    # Entry-point metadata for Task tool (RunSubAgent)
    invoker_type: str | None = None  # Tool-level type mapping (e.g., "general-purpose", "explore", "web")
    invoker_summary: str = ""  # Short description shown under Task tool supported types
    standalone_tool: bool = False  # True for sub-agents invoked by dedicated tools (e.g., ImageGen)

    # UI display
    active_form: str = ""  # Active form for spinner status (e.g., "Tasking", "Exploring")

    # Config-based availability requirement (e.g., "image_model" means requires an image model)
    # The actual check is performed in the core layer to avoid circular imports.
    availability_requirement: str | None = None


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


def is_sub_agent_tool(tool_name: str) -> bool:
    from klaude_code.protocol import tools

    return tool_name in {tools.TASK, tools.IMAGE_GEN}


# Import sub-agent modules to trigger registration
from klaude_code.protocol.sub_agent import explore as explore  # noqa: E402
from klaude_code.protocol.sub_agent import image_gen as image_gen  # noqa: E402
from klaude_code.protocol.sub_agent import task as task  # noqa: E402
from klaude_code.protocol.sub_agent import web as web  # noqa: E402
