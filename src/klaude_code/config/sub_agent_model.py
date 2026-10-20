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

if TYPE_CHECKING:
    from klaude_code.config.config import Config, ModelEntry


@dataclass
class SubAgentModelInfo:
    """Sub-agent and its current model configuration."""

    profile: SubAgentProfile
    # Explicitly configured model selector (from config), if any.
    configured_model: ModelPreference

    # Effective model name used by this sub-agent.
    # - Configured and available: equals configured_model.
    # - Configured but unavailable, or not configured: the main model.
    effective_model: ModelPreference

    # True when configured_model is set but no model in its chain is currently
    # available, so the sub-agent runs on the main model instead.
    falls_back_to_main: bool


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

    def _configured_model_available(self, preference: ModelPreference) -> bool:
        """Whether any model in a configured preference chain is currently usable."""
        try:
            return self._config.get_first_available_model(preference) is not None
        except ValueError:
            # Unknown model, disabled provider, missing credentials, or a provider
            # removed from this build: unavailable for display purposes.
            return False

    def get_available_sub_agents(self) -> list[SubAgentModelInfo]:
        """Return all available sub-agents with their current model config.

        For sub-agents without explicit config, inherit the main model. A sub-agent
        whose configured chain has no available model also ends up on the main model:
        the runtime swallows the resolution error and hands the child the parent's
        model, so the effective model must not claim the configured value.
        """
        result: list[SubAgentModelInfo] = []
        for profile in iter_sub_agent_profiles():
            role_key = profile.name
            configured_model = self._config.sub_agent_models.get(role_key)
            falls_back = configured_model is not None and not self._configured_model_available(configured_model)
            effective_model = self._config.main_model if configured_model is None or falls_back else configured_model
            result.append(
                SubAgentModelInfo(
                    profile=profile,
                    configured_model=configured_model,
                    effective_model=effective_model,
                    falls_back_to_main=falls_back,
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
