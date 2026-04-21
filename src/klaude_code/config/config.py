import asyncio
import difflib
import os
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

type ModelPreference = str | list[str] | None

# Pattern to match ${ENV_VAR} and ${PRIMARY|FALLBACK} syntax
_ENV_VAR_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*(?:\|[A-Za-z_][A-Za-z0-9_]*)*)\}$")
_PROVIDER_NAME_ALIASES = {
    "copilot": "github-copilot",
}


def normalize_provider_name(provider_name: str) -> str:
    return _PROVIDER_NAME_ALIASES.get(provider_name.casefold(), provider_name)


_SUGGESTION_MIN_SCORE = 0.4
_PROVIDER_MATCH_BONUS = 0.3


def _normalize_model_key(value: str) -> str:
    """Casefold and strip non-alphanumerics for loose model name comparison."""

    return "".join(ch for ch in value.casefold() if ch.isalnum())


class ModelAvailability(str, Enum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"
    INVALID_SELECTOR = "invalid_selector"
    NO_MATCHING_PROVIDER = "no_matching_provider"
    PROVIDER_DISABLED = "provider_disabled"
    MISSING_CREDENTIALS = "missing_credentials"
    MODEL_DISABLED = "model_disabled"


@dataclass(frozen=True)
class ModelDiagnosis:
    """Result of diagnosing whether a model selector is usable."""

    availability: ModelAvailability
    detail: str
    suggestions: list[str] = dc_field(default_factory=list[str])

    @property
    def is_available(self) -> bool:
        return self.availability == ModelAvailability.AVAILABLE


def parse_env_var_syntax(value: str | None) -> tuple[str | None, str | None]:
    """Parse a value that may use ${ENV_VAR} syntax.

    Returns:
        A tuple of (env_var_expression, resolved_value).
        - If value uses ${ENV_VAR} or ${A|B} syntax:
          (env_var_expression, resolved_value)
          Priority for each env var: os.environ > klaude-auth.json env section
          For ${A|B}, A is tried first, then B.
        - If value is a plain string: (None, value)
        - If value is None: (None, None)
    """
    if value is None:
        return None, None

    match = _ENV_VAR_PATTERN.match(value)
    if match:
        env_var_expression = match.group(1)
        env_var_names = env_var_expression.split("|")
        resolved = None
        for env_var_name in env_var_names:
            # Priority: real env var > auth.json env section
            resolved = os.environ.get(env_var_name) or get_auth_env(env_var_name)
            if resolved is not None:
                break
        return env_var_expression, resolved

    return None, value


def resolve_api_key(value: str | None) -> str | None:
    """Resolve an API key value, expanding ${ENV_VAR} syntax if present."""
    _, resolved = parse_env_var_syntax(value)
    return resolved


def _normalize_model_preference(value: Any) -> ModelPreference:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, list):
        normalized_list: list[str] = []
        for item in cast(list[object], value):
            s = str(item).strip()
            if s:
                normalized_list.append(s)
        return normalized_list or None
    return value


def _iter_model_preference_values(value: ModelPreference) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def format_model_preference(value: ModelPreference) -> str | None:
    choices = _iter_model_preference_values(value)
    if not choices:
        return None
    return " > ".join(choices)


config_path = Path.home() / ".klaude" / "klaude-config.yaml"
example_config_path = Path.home() / ".klaude" / "klaude-config.example.yaml"


class ModelConfig(llm_param.LLMConfigModelParameter):
    """Model configuration that flattens LLMConfigModelParameter fields."""

    model_name: str = Field(default="", validate_default=True)

    @model_validator(mode="before")
    @classmethod
    def _default_model_name(cls, data: dict[str, Any]) -> dict[str, Any]:
        if not data.get("model_name") and data.get("model_id"):
            data["model_name"] = data["model_id"]
        return data

    @field_validator("model_name")
    @classmethod
    def _validate_model_name(cls, v: str) -> str:
        if not v:
            raise ValueError("model_name or model_id must be provided")
        return v


class ProviderConfig(llm_param.LLMConfigProviderParameter):
    """Full provider configuration (used in merged config)."""

    disabled: bool = False
    model_list: list[ModelConfig] = Field(default_factory=lambda: [])

    @model_validator(mode="before")
    @classmethod
    def _normalize_provider_name_in_model(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, Any], data)
        provider_name = payload.get("provider_name")
        if isinstance(provider_name, str):
            payload["provider_name"] = normalize_provider_name(provider_name)
        return payload

    def get_resolved_api_key(self) -> str | None:
        """Get the resolved API key, expanding ${ENV_VAR} syntax if present."""
        return resolve_api_key(self.api_key)

    def get_api_key_env_var(self) -> str | None:
        """Get the environment variable name if ${ENV_VAR} syntax is used."""
        env_var, _ = parse_env_var_syntax(self.api_key)
        return env_var

    def is_api_key_missing(self) -> bool:
        """Check if the API key is missing (either not set or env var not found).

        For codex protocol, checks OAuth login status instead of API key.
        For bedrock protocol, checks AWS credentials instead of API key.
        For google_vertex protocol, checks Vertex credentials instead of API key.
        """
        from klaude_code.protocol.llm_param import LLMClientProtocol

        if self.protocol == LLMClientProtocol.CODEX_OAUTH:
            # Codex uses OAuth authentication, not API key
            from klaude_code.auth.codex.token_manager import CodexTokenManager

            token_manager = CodexTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in. Token refresh happens on-demand.
            return state is None

        if self.protocol == LLMClientProtocol.GITHUB_COPILOT_OAUTH:
            # GitHub Copilot uses OAuth authentication, not API key
            from klaude_code.auth.copilot.token_manager import CopilotTokenManager

            token_manager = CopilotTokenManager()
            state = token_manager.get_state()
            # Consider available if logged in. Token refresh happens on-demand.
            return state is None

        if self.protocol == LLMClientProtocol.BEDROCK:
            # Bedrock uses AWS credentials, not API key. Region is always required.
            _, resolved_profile = parse_env_var_syntax(self.aws_profile)
            _, resolved_region = parse_env_var_syntax(self.aws_region)

            # When using profile, we still need region to initialize the client.
            if resolved_profile:
                return resolved_region is None

            _, resolved_access_key = parse_env_var_syntax(self.aws_access_key)
            _, resolved_secret_key = parse_env_var_syntax(self.aws_secret_key)
            return resolved_region is None or resolved_access_key is None or resolved_secret_key is None

        if self.protocol == LLMClientProtocol.GOOGLE_VERTEX:
            # Vertex AI requires credentials file, project, and location.
            _, resolved_credentials = parse_env_var_syntax(self.google_application_credentials)
            _, resolved_project = parse_env_var_syntax(self.google_cloud_project)
            _, resolved_location = parse_env_var_syntax(self.google_cloud_location)
            return resolved_credentials is None or resolved_project is None or resolved_location is None

        return self.get_resolved_api_key() is None


class UserProviderConfig(BaseModel):
    """User provider configuration (allows partial overrides).

    Unlike ProviderConfig, protocol is optional here since user may only want
    to add models to an existing builtin provider.
    """

    provider_name: str
    protocol: llm_param.LLMClientProtocol | None = None
    disabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    aws_region: str | None = None
    aws_session_token: str | None = None
    aws_profile: str | None = None
    google_application_credentials: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None
    model_list: list[ModelConfig] = Field(default_factory=lambda: [])

    @model_validator(mode="before")
    @classmethod
    def _normalize_provider_name_in_model(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, Any], data)
        provider_name = payload.get("provider_name")
        if isinstance(provider_name, str):
            payload["provider_name"] = normalize_provider_name(provider_name)
        return payload


class ModelEntry(llm_param.LLMConfigModelParameter):
    """Model entry with provider info, flattens LLMConfigModelParameter fields."""

    model_name: str
    provider: str

    @property
    def selector(self) -> str:
        """Return a provider-qualified model selector.

        This selector can be persisted in user config (e.g. ``sonnet@openrouter``)
        and later resolved via :meth:`Config.get_model_config`.
        """

        return f"{self.model_name}@{self.provider}"


class UserConfig(BaseModel):
    """User configuration (what gets saved to disk)."""

    main_model: str | None = None
    fast_model: str | list[str] | None = None
    compact_model: str | list[str] | None = None
    sub_agent_models: dict[str, ModelPreference] = Field(default_factory=dict)
    theme: str | None = None
    auto_upgrade: bool | None = None
    provider_list: list[UserProviderConfig] = Field(default_factory=lambda: [])

    @model_validator(mode="before")
    @classmethod
    def _normalize_sub_agent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        data["fast_model"] = _normalize_model_preference(data.get("fast_model"))
        data["compact_model"] = _normalize_model_preference(data.get("compact_model"))
        raw_val: Any = data.get("sub_agent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, ModelPreference] = {}
        key_map: dict[str, str] = {}
        for profile in iter_sub_agent_profiles():
            key_map[profile.name.lower()] = profile.name
        for key, value in dict(raw_models).items():
            normalized_key = str(key).strip().lower()
            canonical = key_map.get(normalized_key)
            if canonical is None:
                continue
            normalized_value = _normalize_model_preference(value)
            if normalized_value is None:
                continue
            normalized[canonical] = normalized_value
        data["sub_agent_models"] = normalized
        return data


class Config(BaseModel):
    """Merged configuration (builtin + user) for runtime use."""

    main_model: str | None = None
    fast_model: str | list[str] | None = None
    compact_model: str | list[str] | None = None
    sub_agent_models: dict[str, ModelPreference] = Field(default_factory=dict)
    theme: str | None = None
    auto_upgrade: bool = True
    provider_list: list[ProviderConfig] = Field(default_factory=lambda: [])

    # Internal: reference to original user config for saving
    _user_config: UserConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_sub_agent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        data["fast_model"] = _normalize_model_preference(data.get("fast_model"))
        data["compact_model"] = _normalize_model_preference(data.get("compact_model"))
        raw_val: Any = data.get("sub_agent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, ModelPreference] = {}
        key_map: dict[str, str] = {}
        for profile in iter_sub_agent_profiles():
            key_map[profile.name.lower()] = profile.name
        for key, value in dict(raw_models).items():
            normalized_key = str(key).strip().lower()
            canonical = key_map.get(normalized_key)
            if canonical is None:
                continue
            normalized_value = _normalize_model_preference(value)
            if normalized_value is None:
                continue
            normalized[canonical] = normalized_value
        data["sub_agent_models"] = normalized
        return data

    def set_user_config(self, user_config: UserConfig | None) -> None:
        """Set the user config reference for saving."""
        object.__setattr__(self, "_user_config", user_config)

    def get_user_sub_agent_models(self) -> dict[str, ModelPreference]:
        """Return sub_agent_models from user config only (excludes builtin defaults)."""
        if self._user_config is None:
            return {}
        return self._user_config.sub_agent_models

    def get_first_available_model(self, model_preference: ModelPreference) -> str | None:
        """Resolve a string-or-list model preference to the first available selector."""
        last_error: ValueError | None = None
        for model_name in _iter_model_preference_values(model_preference):
            try:
                _ = self.get_model_config(model_name)
                return model_name
            except ValueError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return None

    @classmethod
    def _split_model_selector(cls, model_selector: str) -> tuple[str, str | None]:
        """Split a model selector into (model_name, provider_name).

        Supported forms:
        - ``sonnet``: unqualified; caller should pick the first matching provider.
        - ``sonnet@openrouter``: provider-qualified.

        Note: the provider segment is normalized for backwards compatibility.
        """

        trimmed = model_selector.strip()
        if "@" not in trimmed:
            return trimmed, None

        base, provider = trimmed.rsplit("@", 1)
        base = base.strip()
        provider = normalize_provider_name(provider.strip())
        if not base or not provider:
            raise ValueError(f"Invalid model selector: {model_selector!r}")
        return base, provider

    def has_model_config_name(self, model_selector: str) -> bool:
        """Return True if the selector points to a configured model.

        This check is configuration-only: it does not require a valid API key or
        OAuth login.
        """

        model_name, provider_name = self._split_model_selector(model_selector)
        if provider_name is not None:
            for provider in self.provider_list:
                if provider.provider_name.casefold() != provider_name.casefold():
                    continue
                return any(m.model_name == model_name for m in provider.model_list)
            return False

        return any(any(m.model_name == model_name for m in provider.model_list) for provider in self.provider_list)

    def diagnose_model(self, model_selector: str, *, max_suggestions: int = 3) -> ModelDiagnosis:
        """Diagnose whether a selector is available and suggest close alternatives.

        Mirrors :meth:`get_model_config`'s acceptance logic, but returns a
        structured reason and a ranked list of similar available selectors
        instead of raising. Intended for startup validation and TUI hints.
        """

        try:
            requested_model, requested_provider = self._split_model_selector(model_selector)
        except ValueError as exc:
            return ModelDiagnosis(
                availability=ModelAvailability.INVALID_SELECTOR,
                detail=str(exc),
                suggestions=self._suggest_models(model_selector, None, max_suggestions=max_suggestions),
            )

        # Track the most informative failure observed across providers. If any
        # path yields AVAILABLE we return immediately; otherwise we surface the
        # recorded failure plus suggestions.
        best_failure: ModelDiagnosis | None = None
        provider_matched = False

        for provider in self.provider_list:
            if requested_provider is not None and provider.provider_name.casefold() != requested_provider.casefold():
                continue
            provider_matched = True
            model_present = any(m.model_name == requested_model for m in provider.model_list)

            if provider.disabled:
                if model_present:
                    best_failure = ModelDiagnosis(
                        availability=ModelAvailability.PROVIDER_DISABLED,
                        detail=f"Provider '{provider.provider_name}' is disabled",
                    )
                continue

            if provider.is_api_key_missing():
                if model_present:
                    best_failure = ModelDiagnosis(
                        availability=ModelAvailability.MISSING_CREDENTIALS,
                        detail=f"Provider '{provider.provider_name}' is missing credentials",
                    )
                continue

            for model in provider.model_list:
                if model.model_name != requested_model:
                    continue
                if model.disabled:
                    best_failure = ModelDiagnosis(
                        availability=ModelAvailability.MODEL_DISABLED,
                        detail=f"Model '{requested_model}' is disabled in provider '{provider.provider_name}'",
                    )
                    break
                return ModelDiagnosis(availability=ModelAvailability.AVAILABLE, detail="")

        suggestions = self._suggest_models(requested_model, requested_provider, max_suggestions=max_suggestions)

        if best_failure is not None:
            return ModelDiagnosis(
                availability=best_failure.availability,
                detail=best_failure.detail,
                suggestions=suggestions,
            )

        if requested_provider is not None and not provider_matched:
            return ModelDiagnosis(
                availability=ModelAvailability.NO_MATCHING_PROVIDER,
                detail=f"Provider '{requested_provider}' is not configured",
                suggestions=suggestions,
            )

        return ModelDiagnosis(
            availability=ModelAvailability.UNKNOWN,
            detail=f"Unknown model: {model_selector}",
            suggestions=suggestions,
        )

    def _suggest_models(
        self,
        requested_model: str,
        requested_provider: str | None,
        *,
        max_suggestions: int = 3,
    ) -> list[str]:
        """Return top-N available selectors ranked by model-name similarity.

        Candidates from the same provider as ``requested_provider`` receive a
        bonus so version drifts like ``gpt-5.2@openai`` -> ``gpt-5.4@openai``
        are preferred over same-name matches under a different provider.
        """

        candidates = self.iter_model_entries(only_available=True, include_disabled=False)
        if not candidates:
            return []

        requested_norm = _normalize_model_key(requested_model)
        requested_provider_cf = requested_provider.casefold() if requested_provider else None

        scored: list[tuple[float, str]] = []
        for cand in candidates:
            raw_ratio = difflib.SequenceMatcher(None, requested_model, cand.model_name).ratio()
            norm_ratio = difflib.SequenceMatcher(None, requested_norm, _normalize_model_key(cand.model_name)).ratio()
            score = max(raw_ratio, norm_ratio)
            if requested_provider_cf and cand.provider.casefold() == requested_provider_cf:
                score += _PROVIDER_MATCH_BONUS
            if score >= _SUGGESTION_MIN_SCORE:
                scored.append((score, cand.selector))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        seen: set[str] = set()
        results: list[str] = []
        for _, selector in scored:
            if selector in seen:
                continue
            seen.add(selector)
            results.append(selector)
            if len(results) >= max_suggestions:
                break
        return results

    def resolve_model_location(self, model_selector: str) -> tuple[str, str] | None:
        """Resolve a selector to (model_name, provider_name), without auth checks.

        - If the selector is provider-qualified, returns that provider.
        - If unqualified, returns the first provider that defines the model.
        """

        model_name, provider_name = self._split_model_selector(model_selector)
        if provider_name is not None:
            for provider in self.provider_list:
                if provider.provider_name.casefold() != provider_name.casefold():
                    continue
                if any(m.model_name == model_name for m in provider.model_list):
                    return model_name, provider.provider_name
            return None

        for provider in self.provider_list:
            if any(m.model_name == model_name for m in provider.model_list):
                return model_name, provider.provider_name
        return None

    def resolve_model_location_prefer_available(self, model_selector: str) -> tuple[str, str] | None:
        """Resolve a selector to (model_name, provider_name), preferring usable providers.

        This uses the same availability logic as :meth:`get_model_config`.
        """

        requested_model, requested_provider = self._split_model_selector(model_selector)

        for provider in self.provider_list:
            if requested_provider is not None and provider.provider_name.casefold() != requested_provider.casefold():
                continue

            if provider.disabled or provider.is_api_key_missing():
                continue

            for model in provider.model_list:
                if model.model_name != requested_model:
                    continue
                if model.disabled:
                    continue
                return requested_model, provider.provider_name

        return None

    def get_model_config(self, model_name: str) -> llm_param.LLMConfigParameter:
        requested_model, requested_provider = self._split_model_selector(model_name)

        for provider in self.provider_list:
            if requested_provider is not None and provider.provider_name.casefold() != requested_provider.casefold():
                continue

            if provider.disabled:
                if requested_provider is not None:
                    raise ValueError(f"Provider '{provider.provider_name}' is disabled for: {model_name}")
                continue

            if provider.is_api_key_missing():
                if requested_provider is not None:
                    raise ValueError(
                        f"Provider '{provider.provider_name}' is not available (missing credentials) for: {model_name}"
                    )
                continue

            for model in provider.model_list:
                if model.model_name != requested_model:
                    continue

                if model.disabled:
                    if requested_provider is not None:
                        raise ValueError(
                            f"Model '{requested_model}' is disabled in provider '{provider.provider_name}' for: {model_name}"
                        )
                    break

                provider_dump = provider.model_dump(exclude={"model_list", "disabled"})
                provider_dump["api_key"] = provider.get_resolved_api_key()
                for field in (
                    "aws_access_key",
                    "aws_secret_key",
                    "aws_region",
                    "aws_session_token",
                    "aws_profile",
                    "google_application_credentials",
                    "google_cloud_project",
                    "google_cloud_location",
                ):
                    _, provider_dump[field] = parse_env_var_syntax(provider_dump.get(field))
                return llm_param.LLMConfigParameter(
                    **provider_dump,
                    **model.model_dump(exclude={"model_name"}),
                )

        raise ValueError(f"Unknown model: {model_name}")

    def iter_model_entries(self, only_available: bool = False, include_disabled: bool = True) -> list[ModelEntry]:
        """Return all model entries with their provider names.

        Args:
            only_available: If True, only return models from providers with valid API keys.
            include_disabled: If False, exclude models/providers with disabled=True.
        """
        return [
            ModelEntry(
                model_name=model.model_name,
                provider=provider.provider_name,
                **model.model_dump(exclude={"model_name"}),
            )
            for provider in self.provider_list
            if include_disabled or not provider.disabled
            if not only_available or (not provider.disabled and not provider.is_api_key_missing())
            for model in provider.model_list
            if include_disabled or not model.disabled
        ]

    async def save(self) -> None:
        """Save user config to file (excludes builtin providers).

        Only saves user-specific settings like main_model and custom providers.
        Builtin providers are never written to the user config file.
        Values that match builtin defaults are omitted to keep the file minimal.
        """
        # Get user config, creating one if needed
        user_config = self._user_config
        if user_config is None:
            user_config = UserConfig()

        builtin = get_builtin_config()

        # Only save values that differ from builtin defaults
        user_config.main_model = self.main_model if self.main_model != builtin.main_model else None
        user_config.fast_model = self.fast_model if self.fast_model != builtin.fast_model else None
        user_config.compact_model = self.compact_model if self.compact_model != builtin.compact_model else None
        user_config.theme = self.theme if self.theme != builtin.theme else None
        user_config.auto_upgrade = self.auto_upgrade if self.auto_upgrade != builtin.auto_upgrade else None

        # For sub_agent_models, only save entries that differ from builtin
        user_sub_agent_models: dict[str, ModelPreference] = {}
        for key, value in self.sub_agent_models.items():
            if builtin.sub_agent_models.get(key) != value:
                user_sub_agent_models[key] = value
        user_config.sub_agent_models = user_sub_agent_models
        # Note: provider_list is NOT synced - user providers are already in user_config

        # Keep the saved file compact (exclude defaults), but preserve explicit
        # overrides inside provider_list (e.g. `disabled: false` to re-enable a
        # builtin provider that is disabled by default).
        config_dict = user_config.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
            exclude={"provider_list"},
        )

        provider_list = [
            p.model_dump(mode="json", exclude_none=True, exclude_unset=True) for p in user_config.provider_list
        ]
        if provider_list:
            config_dict["provider_list"] = provider_list

        def _save_config() -> None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
            config_path.write_text(yaml_content or "")

        await asyncio.to_thread(_save_config)
