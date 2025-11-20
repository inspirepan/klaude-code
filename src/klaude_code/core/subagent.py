from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from klaude_code.protocol import tools

AvailabilityPredicate = Callable[[str], bool]


@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False


@dataclass(frozen=True)
class SubAgentProfile:
    """Metadata describing a sub agent and how it integrates with the system."""

    type: tools.SubAgentType
    tool_name: str
    prompt_key: str
    config_key: str
    tool_set: tuple[str, ...]
    enabled_by_default: bool = True
    show_in_main_agent: bool = True
    target_model_filter: AvailabilityPredicate | None = None

    def enabled_for_model(self, model_name: str | None) -> bool:
        if not self.enabled_by_default:
            return False
        if model_name is None or self.target_model_filter is None:
            return True
        return self.target_model_filter(model_name)


_PROFILES: dict[tools.SubAgentType, SubAgentProfile] = {}
_PROFILES_BY_TOOL: dict[str, SubAgentProfile] = {}


def register_sub_agent(profile: SubAgentProfile) -> None:
    if profile.type in _PROFILES:
        raise ValueError(f"Duplicate sub agent profile: {profile.type}")
    _PROFILES[profile.type] = profile
    _PROFILES_BY_TOOL[profile.tool_name] = profile


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
    return _PROFILES_BY_TOOL.get(tool_name)


def is_sub_agent_tool(tool_name: str) -> bool:
    return tool_name in _PROFILES_BY_TOOL


def sub_agent_tool_names(enabled_only: bool = False, model_name: str | None = None) -> list[str]:
    return [
        profile.tool_name
        for profile in iter_sub_agent_profiles(enabled_only=enabled_only, model_name=model_name)
        if profile.show_in_main_agent
    ]


register_sub_agent(
    SubAgentProfile(
        type=tools.SubAgentType.TASK,
        tool_name=tools.TASK,
        prompt_key="subagent",
        config_key="Task",
        tool_set=(tools.BASH, tools.READ, tools.EDIT),
    )
)
register_sub_agent(
    SubAgentProfile(
        type=tools.SubAgentType.ORACLE,
        tool_name=tools.ORACLE,
        prompt_key="oracle",
        config_key="Oracle",
        tool_set=(tools.READ, tools.BASH),
        target_model_filter=lambda model: ("gpt-5" not in model) and ("gemini-3" not in model),
    )
)
register_sub_agent(
    SubAgentProfile(
        type=tools.SubAgentType.EXPLORE,
        tool_name=tools.EXPLORE,
        prompt_key="subagent_explore",
        config_key="Explore",
        tool_set=(tools.BASH, tools.READ),
        target_model_filter=lambda model: True,
    )
)
