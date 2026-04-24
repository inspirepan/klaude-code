"""Sub-agent model availability and selection logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from klaude_code.config.config import ModelPreference, format_model_preference
from klaude_code.protocol.sub_agent import (
    SubAgentProfile,
    get_sub_agent_profile,
    iter_sub_agent_profiles,
)
from klaude_code.protocol.tools import SubAgentType

if TYPE_CHECKING:
    from klaude_code.config.config import Config, ModelConfigCandidate, ModelEntry


@dataclass
class SubAgentModelInfo:
    """Sub-agent and its current model configuration."""

    profile: SubAgentProfile
    # Explicitly configured model selector (from config), if any.
    configured_model: ModelPreference

    # Effective model name used by this sub-agent.
    # - When configured_model is set: equals configured_model.
    # - When inheriting from defaults: resolved model name.
    effective_model: ModelPreference


@dataclass(frozen=True, slots=True)
class EmptySubAgentModelBehavior:
    """Human-facing description for an unset (empty) sub-agent model config."""

    # Summary text for UI (kept UI-framework agnostic).
    description: str

    # Best-effort resolved model name (if any).
    resolved_model_name: str | None


class SubAgentModelResolver:
    """Sub-agent model availability and selection."""

    def __init__(self, config: Config) -> None:
        self._config = config

    @staticmethod
    def _role_key_for_sub_agent_type(sub_agent_type: str) -> str:
        profile = get_sub_agent_profile(sub_agent_type)
        return profile.name

    def describe_empty_model_config_behavior(
        self,
        sub_agent_type: str,
        *,
        main_model_name: str,
    ) -> EmptySubAgentModelBehavior:
        """Describe what happens when a sub-agent model is not configured.

        Sub-agents inherit the main model when there is no explicit role config.
        """

        role_key = self._role_key_for_sub_agent_type(sub_agent_type)
        role_model = self._config.sub_agent_models.get(role_key)
        resolved = format_model_preference(role_model) or main_model_name
        return EmptySubAgentModelBehavior(
            description=f"use default behavior: {resolved}",
            resolved_model_name=resolved,
        )

    def get_available_sub_agents(self) -> list[SubAgentModelInfo]:
        """Return all available sub-agents with their current model config.

        For sub-agents without explicit config, inherit the main model.
        """
        result: list[SubAgentModelInfo] = []
        for profile in iter_sub_agent_profiles():
            role_key = profile.name
            configured_model = self._config.sub_agent_models.get(role_key)
            effective_model = configured_model or self._config.main_model
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
        """Return single model names for sub-agents that need dedicated clients."""
        result: dict[SubAgentType, str] = {}
        for profile in iter_sub_agent_profiles():
            role_key = profile.name
            model_pref = self._config.sub_agent_models.get(role_key)
            if model_pref is None:
                continue
            if isinstance(model_pref, str):
                result[profile.name] = model_pref
            else:
                # list[str]: resolve to first available model
                try:
                    resolved = self._config.get_first_available_model(model_pref)
                except ValueError:
                    continue
                if resolved is not None:
                    result[profile.name] = resolved
        return result

    def build_sub_agent_client_candidates(self) -> dict[SubAgentType, list[ModelConfigCandidate]]:
        """Return fallback candidate chains for sub-agents that need dedicated clients."""

        result: dict[SubAgentType, list[ModelConfigCandidate]] = {}
        for profile in iter_sub_agent_profiles():
            role_key = profile.name
            model_pref = self._config.sub_agent_models.get(role_key)
            if model_pref is None:
                continue
            candidates = self._config.iter_model_config_candidates(model_pref)
            if candidates:
                result[profile.name] = candidates
        return result
