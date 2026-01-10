"""Helper for sub-agent model availability and selection logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import (
    AVAILABILITY_IMAGE_MODEL,
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
    # - When requirement-based default applies (e.g. ImageGen): resolved model.
    # - When inheriting from defaults: resolved model name.
    effective_model: str | None


@dataclass(frozen=True, slots=True)
class EmptySubAgentModelBehavior:
    """Human-facing description for an unset (empty) sub-agent model config."""

    # Summary text for UI (kept UI-framework agnostic).
    description: str

    # Best-effort resolved model name (if any). For ImageGen this is usually the
    # first available image model; for other sub-agents it's the main model.
    resolved_model_name: str | None


class SubAgentModelHelper:
    """Centralized logic for sub-agent availability and model selection."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def check_availability_requirement(self, requirement: str | None) -> bool:
        """Check if a sub-agent's availability requirement is met.

        Args:
            requirement: The availability requirement constant (e.g., AVAILABILITY_IMAGE_MODEL).

        Returns:
            True if the requirement is met or if there's no requirement.
        """
        if requirement is None:
            return True

        if requirement == AVAILABILITY_IMAGE_MODEL:
            return self._config.has_available_image_model()

        return True

    def resolve_model_for_requirement(self, requirement: str | None) -> str | None:
        """Resolve the model name for a given availability requirement.

        Args:
            requirement: The availability requirement constant.

        Returns:
            The model name if found, None otherwise.
        """
        if requirement == AVAILABILITY_IMAGE_MODEL:
            return self._config.get_first_available_image_model()
        return None

    def resolve_default_model_override(self, sub_agent_type: str) -> str | None:
        """Resolve the default model override for a sub-agent when unset.

        Returns:
            - None for sub-agents that default to inheriting the main agent.
            - A model name for sub-agents that require a dedicated model (e.g. ImageGen).

        Note: This intentionally ignores any explicit user config; callers use this
        when they want the *unset* behavior.
        """

        profile = get_sub_agent_profile(sub_agent_type)
        if profile.availability_requirement is None:
            return None
        return self.resolve_model_for_requirement(profile.availability_requirement)

    def describe_empty_model_config_behavior(
        self,
        sub_agent_type: str,
        *,
        main_model_name: str,
    ) -> EmptySubAgentModelBehavior:
        """Describe what happens when a sub-agent model is not configured.

        Most sub-agents default to the Task model if configured, otherwise
        they inherit the main model.

        Sub-agents with an availability requirement (e.g. ImageGen) do NOT
        inherit from Task/main; instead they auto-resolve a suitable model
        (currently: the first available image model).
        """

        profile = get_sub_agent_profile(sub_agent_type)

        requirement = profile.availability_requirement
        if requirement is None:
            task_model = self._config.sub_agent_models.get(tools.TASK)
            resolved = task_model or main_model_name
            return EmptySubAgentModelBehavior(
                description=f"use default behavior: {resolved}",
                resolved_model_name=resolved,
            )

        resolved = self.resolve_model_for_requirement(requirement)
        if requirement == AVAILABILITY_IMAGE_MODEL:
            if resolved:
                return EmptySubAgentModelBehavior(
                    description=f"auto-select first available image model: {resolved}",
                    resolved_model_name=resolved,
                )
            return EmptySubAgentModelBehavior(
                description="auto-select first available image model",
                resolved_model_name=None,
            )

        if resolved:
            return EmptySubAgentModelBehavior(
                description=f"auto-select model for requirement '{requirement}': {resolved}",
                resolved_model_name=resolved,
            )
        return EmptySubAgentModelBehavior(
            description=f"auto-select model for requirement '{requirement}'",
            resolved_model_name=None,
        )

    def get_available_sub_agents(self) -> list[SubAgentModelInfo]:
        """Return all available sub-agents with their current model config.

        Only returns sub-agents that:
        1. Are enabled by default
        2. Have their availability requirements met

        For sub-agents without explicit config, resolves model based on availability_requirement.
        """
        result: list[SubAgentModelInfo] = []
        for profile in iter_sub_agent_profiles():
            if not self.check_availability_requirement(profile.availability_requirement):
                continue
            configured_model = self._config.sub_agent_models.get(profile.name)
            effective_model = configured_model
            if not effective_model and profile.availability_requirement:
                effective_model = self.resolve_model_for_requirement(profile.availability_requirement)
            if not effective_model and profile.availability_requirement is None:
                effective_model = self._config.sub_agent_models.get(tools.TASK) or self._config.main_model
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

        For sub-agents with availability_requirement (e.g., ImageGen):
        - Only returns models matching the requirement (e.g., image models)

        For other sub-agents:
        - Returns all available models
        """
        profile = get_sub_agent_profile(sub_agent_type)
        all_models = self._config.iter_model_entries(only_available=True, include_disabled=False)

        if profile.availability_requirement == AVAILABILITY_IMAGE_MODEL:
            return [m for m in all_models if m.modalities and "image" in m.modalities]

        return all_models

    def get_enabled_sub_agent_tool_names(self) -> list[str]:
        """Return sub-agent tool names that should be added to main agent's tool list."""
        result: list[str] = [tools.TASK]
        if self.check_availability_requirement(AVAILABILITY_IMAGE_MODEL):
            result.append(tools.IMAGE_GEN)
        return result

    def build_sub_agent_client_configs(self) -> dict[SubAgentType, str]:
        """Return model names for each sub-agent that needs a dedicated client."""
        result: dict[SubAgentType, str] = {}
        for profile in iter_sub_agent_profiles():
            model_name = self._config.sub_agent_models.get(profile.name)
            if not model_name and profile.availability_requirement:
                model_name = self.resolve_model_for_requirement(profile.availability_requirement)
            if model_name:
                result[profile.name] = model_name
        task_model = self._config.sub_agent_models.get(tools.TASK)
        if task_model:
            result.setdefault(tools.TASK, task_model)
        return result
