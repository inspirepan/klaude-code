"""LLM client containers and factory functions."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import override

from klaude_code.config import Config, load_config
from klaude_code.config.builtin_config import get_builtin_config
from klaude_code.config.config import ModelConfigCandidate, ModelPreference, format_model_preference
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.protocol.tools import SubAgentType


def _default_sub_clients() -> dict[SubAgentType, LLMClientABC]:
    return {}


# Credential fields excluded when dumping LLM configs into the debug log; the
# server writes that log unconditionally, so plaintext keys must never land in it.
_LLM_CONFIG_SECRET_FIELDS = llm_param.LLM_CONFIG_SECRET_FIELDS


class ModelResolutionError(ValueError):
    """Raised when a configured model preference cannot be resolved.

    Carries which role (main/fast/compact/sub-agent) failed so callers can
    produce a precise error message instead of conflating roles.
    """

    def __init__(self, role: str, model_preference: ModelPreference, original: Exception) -> None:
        self.role = role
        self.model_preference = model_preference
        self.original = original
        pref_text = format_model_preference(model_preference) or "<unset>"
        super().__init__(f"{role} '{pref_text}' could not be resolved: {original}")


@dataclass(frozen=True)
class ModelFallback:
    """A runtime switch from one concrete model candidate to another."""

    from_candidate: ModelConfigCandidate
    to_candidate: ModelConfigCandidate


class FallbackLLMClient(LLMClientABC):
    """LLM client wrapper that lazily creates concrete clients and can switch candidates."""

    def __init__(self, candidates: list[ModelConfigCandidate]) -> None:
        if not candidates:
            raise ValueError("FallbackLLMClient requires at least one candidate")
        self._candidates = candidates
        self._active_index = 0
        self._clients: dict[int, LLMClientABC] = {}
        self._client_lock = threading.Lock()
        super().__init__(candidates[0].llm_config)

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del cls
        del config
        raise NotImplementedError("FallbackLLMClient must be constructed with candidates")

    @property
    def active_candidate(self) -> ModelConfigCandidate:
        return self._candidates[self._active_index]

    @property
    def has_next_candidate(self) -> bool:
        return self._active_index + 1 < len(self._candidates)

    @property
    def candidates(self) -> list[ModelConfigCandidate]:
        return list(self._candidates)

    def fallback_to_next(self) -> ModelFallback | None:
        with self._client_lock:
            if not self.has_next_candidate:
                return None
            from_candidate = self.active_candidate
            self._active_index += 1
            to_candidate = self.active_candidate
            self._config = to_candidate.llm_config
        log_debug(
            f"Fallback model config: {from_candidate.selector} -> {to_candidate.selector}",
            debug_type=DebugType.LLM_CONFIG,
        )
        return ModelFallback(from_candidate=from_candidate, to_candidate=to_candidate)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        disabled_reason = await asyncio.to_thread(self._disabled_by_current_config)
        if disabled_reason is not None:
            metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)
            return error_llm_stream(
                metadata_tracker,
                error=(
                    f"model_not_available: {self.active_candidate.selector}: {disabled_reason} (see /manage-providers)"
                ),
            )
        try:
            client = self._clients.get(self._active_index)
            if client is None:
                client = await asyncio.to_thread(self._active_client)
        except Exception as exc:
            metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)
            return error_llm_stream(
                metadata_tracker,
                error=f"model_not_available: failed to initialize {self.active_candidate.selector}: {exc}",
            )
        return await client.call(param)

    def _disabled_by_current_config(self) -> str | None:
        """Call-time disable check so provider toggles reach live sessions.

        Candidates snapshot their provider config at build time, so a
        /manage-providers change would otherwise never affect an already-built
        client. The "model_not_available" error it produces is fallbackable:
        the task loop advances the chain and retries. Runs off the event loop
        because load_config() re-reads the file after a cache clear.
        """
        candidate = self.active_candidate
        try:
            config = load_config()
        except Exception:
            return None  # an unreadable config must not block live sessions
        return config.get_candidate_disabled_reason(
            provider_name=candidate.provider,
            model_name=candidate.model_name,
        )

    async def warmup(self) -> None:
        """Best-effort creation of the active provider client off the event loop."""
        if self._active_index not in self._clients:
            # The first real call preserves the normal error-stream and fallback path.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._active_client)

    def _active_client(self) -> LLMClientABC:
        with self._client_lock:
            client = self._clients.get(self._active_index)
            if client is None:
                candidate = self.active_candidate
                log_debug(
                    "Creating fallback LLM client",
                    candidate.selector,
                    candidate.llm_config.model_dump_json(exclude_none=True, exclude=_LLM_CONFIG_SECRET_FIELDS),
                    debug_type=DebugType.LLM_CONFIG,
                )
                client = create_llm_client(candidate.llm_config)
                self._clients[self._active_index] = client
            return client


def create_llm_client_for_candidates(candidates: list[ModelConfigCandidate]) -> LLMClientABC:
    if not candidates:
        raise ValueError("At least one model candidate is required")
    return FallbackLLMClient(candidates)


@dataclass
class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    main: LLMClientABC
    main_model_alias: str = ""
    sub_clients: dict[SubAgentType, LLMClientABC] = dataclass_field(default_factory=_default_sub_clients)
    fast: LLMClientABC | None = None
    compact: LLMClientABC | None = None
    # Configured models that did not resolve and were replaced by a fallback,
    # e.g. a model an upgrade removed from the builtin list.
    warnings: list[str] = dataclass_field(default_factory=list[str])

    def get_compact_client(self) -> LLMClientABC:
        return self.compact or self.main

    def get_fast_client(self) -> LLMClientABC:
        return self.fast or self.main

    async def warmup(self) -> None:
        """Warm the client needed by the first interactive request."""
        if isinstance(self.main, FallbackLLMClient):
            await self.main.warmup()


def _resolution_error_detail(config: Config, model_pref: ModelPreference) -> str:
    try:
        _ = config.get_first_available_model(model_pref)
    except ValueError as exc:
        return str(exc)
    return "no available candidates"


def _unresolved_warning(role: str, model_pref: ModelPreference, detail: str, fallback: str) -> str:
    pref_text = format_model_preference(model_pref) or "<unset>"
    return f"{role} '{pref_text}' is unavailable ({detail}); {fallback}. Run `klaude conf` to update it."


def _resolve_optional_role(
    config: Config,
    role: str,
    model_pref: ModelPreference | None,
    builtin_pref: ModelPreference | None,
    *,
    inherit_label: str,
    warnings: list[str],
) -> list[ModelConfigCandidate]:
    """Resolve a non-main model role, degrading to the builtin default or inheritance.

    A config that names a model this build no longer ships must not take the
    whole runtime down: the role falls back and the caller surfaces a warning.
    """
    if model_pref is None:
        return []
    candidates = config.iter_model_config_candidates(model_pref)
    if candidates:
        return candidates
    if model_pref == builtin_pref:
        # Builtin defaults often name providers the user never set up; inheriting
        # quietly is the intended behavior there, not a config problem.
        log_debug(f"{role} builtin default unavailable; {inherit_label} is used", debug_type=DebugType.LLM_CONFIG)
        return []
    detail = _resolution_error_detail(config, model_pref)
    if builtin_pref is not None:
        builtin_candidates = config.iter_model_config_candidates(builtin_pref)
        if builtin_candidates:
            fallback = f"using builtin default '{builtin_candidates[0].selector}'"
            warnings.append(_unresolved_warning(role, model_pref, detail, fallback))
            return builtin_candidates
    warnings.append(_unresolved_warning(role, model_pref, detail, f"falling back to {inherit_label}"))
    return []


def _resolve_main_candidates(
    config: Config,
    model_override: str | None,
    warnings: list[str],
) -> tuple[list[ModelConfigCandidate], str]:
    model_pref: ModelPreference = model_override or config.main_model
    if model_pref is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    main_candidates = (
        config.iter_model_config_candidates_with_preference_fallback(model_override, config.main_model)
        if model_override is not None
        else config.iter_model_config_candidates(model_pref)
    )
    if main_candidates:
        model_name = (
            format_model_preference([candidate.selector for candidate in main_candidates])
            if model_override is not None and len(main_candidates) > 1
            else format_model_preference(model_pref)
        ) or main_candidates[0].selector
        return main_candidates, model_name

    detail = _resolution_error_detail(config, model_pref)
    if model_override is not None:
        # An explicit --model is a direct request; substituting another model
        # would silently ignore it.
        raise ModelResolutionError("main_model", model_pref, ValueError(detail))

    builtin_pref = get_builtin_config().main_model
    fallback_candidates = config.iter_model_config_candidates(builtin_pref) if builtin_pref is not None else []
    if not fallback_candidates:
        available = config.iter_model_entries(only_available=True, include_disabled=False)
        if available:
            fallback_candidates = config.iter_model_config_candidates(available[0].selector)
    if not fallback_candidates:
        raise ModelResolutionError("main_model", model_pref, ValueError(detail))
    selector = fallback_candidates[0].selector
    warnings.append(_unresolved_warning("main_model", model_pref, detail, f"using '{selector}'"))
    return fallback_candidates, selector


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    skip_sub_agents: bool = False,
) -> LLMClients:
    warnings: list[str] = []
    builtin = get_builtin_config()
    main_candidates, model_name = _resolve_main_candidates(config, model_override, warnings)
    llm_config = main_candidates[0].llm_config

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True, exclude=_LLM_CONFIG_SECRET_FIELDS),
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client_for_candidates(main_candidates)

    fast_client: LLMClientABC | None = None
    fast_candidates = _resolve_optional_role(
        config,
        "fast_model",
        config.fast_model,
        builtin.fast_model,
        inherit_label="the main model",
        warnings=warnings,
    )
    if fast_candidates:
        # The fast role uses a single concrete model, no fallback chain.
        fast_candidate = fast_candidates[0]
        log_debug(
            "Fast LLM config",
            fast_candidate.llm_config.model_dump_json(exclude_none=True, exclude=_LLM_CONFIG_SECRET_FIELDS),
            debug_type=DebugType.LLM_CONFIG,
        )
        fast_client = create_llm_client_for_candidates([fast_candidate])

    compact_client: LLMClientABC | None = None
    compact_candidates = _resolve_optional_role(
        config,
        "compact_model",
        config.compact_model,
        builtin.compact_model,
        inherit_label="the main model",
        warnings=warnings,
    )
    if compact_candidates:
        log_debug(
            "Compact LLM config",
            compact_candidates[0].llm_config.model_dump_json(exclude_none=True, exclude=_LLM_CONFIG_SECRET_FIELDS),
            debug_type=DebugType.LLM_CONFIG,
        )
        compact_client = create_llm_client_for_candidates(compact_candidates)

    if skip_sub_agents:
        return LLMClients(
            main=main_client,
            main_model_alias=model_name,
            fast=fast_client,
            compact=compact_client,
            warnings=warnings,
        )

    sub_clients: dict[SubAgentType, LLMClientABC] = {}
    for profile in iter_sub_agent_profiles():
        role_key = profile.name
        candidates = _resolve_optional_role(
            config,
            f"sub_agent_models.{role_key}",
            config.sub_agent_models.get(role_key),
            builtin.sub_agent_models.get(role_key),
            inherit_label="the main model",
            warnings=warnings,
        )
        if candidates:
            sub_clients[profile.name] = FallbackLLMClient(candidates)

    return LLMClients(
        main=main_client,
        main_model_alias=model_name,
        sub_clients=sub_clients,
        fast=fast_client,
        compact=compact_client,
        warnings=warnings,
    )


def collect_model_config_warnings(config: Config) -> list[str]:
    """Report configured models that do not resolve, without failing.

    Clients are created lazily, so building them only to read the warnings
    makes no network calls.
    """
    try:
        return build_llm_clients(config).warnings
    except ValueError as exc:
        return [str(exc)]


def clone_llm_client(client: LLMClientABC) -> LLMClientABC:
    if isinstance(client, FallbackLLMClient):
        return FallbackLLMClient(
            [
                ModelConfigCandidate(
                    selector=candidate.selector,
                    model_name=candidate.model_name,
                    provider=candidate.provider,
                    llm_config=candidate.llm_config.model_copy(deep=True),
                )
                for candidate in client.candidates
            ]
        )
    return create_llm_client(client.get_llm_config().model_copy(deep=True))


def clone_llm_clients(template: LLMClients) -> LLMClients:
    return LLMClients(
        main=clone_llm_client(template.main),
        main_model_alias=template.main_model_alias,
        sub_clients={
            sub_agent_type: clone_llm_client(client) for sub_agent_type, client in template.sub_clients.items()
        },
        fast=clone_llm_client(template.fast) if template.fast is not None else None,
        compact=clone_llm_client(template.compact) if template.compact is not None else None,
    )
