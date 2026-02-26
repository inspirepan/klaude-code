"""Helper for sub-agent model availability and selection logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import (
    SubAgentProfile,
    get_sub_agent_profile,
    iter_sub_agent_profiles,
)
from klaude_code.protocol.tools import SubAgentType

if TYPE_CHECKING:
    from klaude_code.config.config import Config, ModelEntry


@dataclass
class SubAgentModelInfo:
    """Sub-agent and its current model configuration."""

    profile: SubAgentProfile
    # Explicitly configured model selector (from config), if any.
    configured_model: str | None

    # Effective model name used by this sub-agent.
    # - When configured_model is set: equals configured_model.
    # - When inheriting from defaults: resolved model name.
    effective_model: str | None


@dataclass(frozen=True, slots=True)
class EmptySubAgentModelBehavior:
    """Human-facing description for an unset (empty) sub-agent model config."""

    # Summary text for UI (kept UI-framework agnostic).
    description: str

    # Best-effort resolved model name (if any).
    resolved_model_name: str | None


class SubAgentModelHelper:
    """Centralized logic for sub-agent availability and model selection."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def describe_empty_model_config_behavior(
        self,
        sub_agent_type: str,
        *,
        main_model_name: str,
    ) -> EmptySubAgentModelBehavior:
        """Describe what happens when a sub-agent model is not configured.

        Sub-agents default to the Task model if configured, otherwise
        they inherit the main model.
        """

        _ = get_sub_agent_profile(sub_agent_type)
        task_model = self._config.sub_agent_models.get(tools.TASK)
        resolved = task_model or main_model_name
        return EmptySubAgentModelBehavior(
            description=f"use default behavior: {resolved}",
            resolved_model_name=resolved,
        )

    def get_available_sub_agents(self) -> list[SubAgentModelInfo]:
        """Return all available sub-agents with their current model config.

        For sub-agents without explicit config, resolve from Task/main defaults.
        """
        result: list[SubAgentModelInfo] = []
        for profile in iter_sub_agent_profiles():
            configured_model = self._config.sub_agent_models.get(profile.name)
            effective_model = (
                configured_model or self._config.sub_agent_models.get(tools.TASK) or self._config.main_model
            )
            result.append(
                SubAgentModelInfo(
                    profile=profile,
                    configured_model=configured_model,
                    effective_model=effective_model,
                )
            )
        return result

    def get_selectable_models(self, sub_agent_type: str) -> list[ModelEntry]:
        """Return selectable models for a specific sub-agent type.

        Returns all available models.
        """
        _ = get_sub_agent_profile(sub_agent_type)
        all_models = self._config.iter_model_entries(only_available=True, include_disabled=False)
        return all_models

    def build_sub_agent_client_configs(self) -> dict[SubAgentType, str]:
        """Return model names for each sub-agent that needs a dedicated client."""
        result: dict[SubAgentType, str] = {}
        for profile in iter_sub_agent_profiles():
            model_name = self._config.sub_agent_models.get(profile.name)
            if model_name:
                result[profile.name] = model_name
        task_model = self._config.sub_agent_models.get(tools.TASK)
        if task_model:
            result.setdefault(tools.TASK, task_model)
        return result
