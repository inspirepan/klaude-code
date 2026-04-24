"""LLM client containers and factory functions."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import override

from klaude_code.config import Config
from klaude_code.config.config import ModelConfigCandidate, ModelPreference, format_model_preference
from klaude_code.config.sub_agent_model import SubAgentModelResolver
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType


def _default_sub_clients() -> dict[SubAgentType, LLMClientABC]:
    return {}


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
        super().__init__(candidates[0].llm_config)

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
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
        try:
            client = self._active_client()
        except Exception as exc:
            metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)
            return error_llm_stream(
                metadata_tracker,
                error=f"model_not_available: failed to initialize {self.active_candidate.selector}: {exc}",
            )
        return await client.call(param)

    def _active_client(self) -> LLMClientABC:
        client = self._clients.get(self._active_index)
        if client is None:
            candidate = self.active_candidate
            log_debug(
                "Creating fallback LLM client",
                candidate.selector,
                candidate.llm_config.model_dump_json(exclude_none=True),
                debug_type=DebugType.LLM_CONFIG,
            )
            client = create_llm_client(candidate.llm_config)
            self._clients[self._active_index] = client
        return client


@dataclass
class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    main: LLMClientABC
    main_model_alias: str = ""
    sub_clients: dict[SubAgentType, LLMClientABC] = dataclass_field(default_factory=_default_sub_clients)
    fast: LLMClientABC | None = None
    compact: LLMClientABC | None = None

    def get_client(self, sub_agent_type: SubAgentType | None = None) -> LLMClientABC:
        if sub_agent_type is None:
            return self.main
        client = self.sub_clients.get(sub_agent_type)
        if client is not None:
            return client
        return self.main

    def get_compact_client(self) -> LLMClientABC:
        return self.compact or self.main

    def get_fast_client(self) -> LLMClientABC:
        return self.fast or self.main


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    skip_sub_agents: bool = False,
) -> LLMClients:
    model_pref: ModelPreference = model_override or config.main_model
    if model_pref is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    main_candidates = config.iter_model_config_candidates(model_pref)
    if not main_candidates:
        _ = config.get_first_available_model(model_pref)
        raise ValueError("No available main_model candidates")
    llm_config = main_candidates[0].llm_config
    model_name = format_model_preference(model_pref) or main_candidates[0].selector

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = FallbackLLMClient(main_candidates) if len(main_candidates) > 1 else create_llm_client(llm_config)

    fast_client: LLMClientABC | None = None
    selected_fast_model = config.get_first_available_model(config.fast_model)
    if selected_fast_model is not None:
        fast_llm_config = config.get_model_config(selected_fast_model)
        log_debug(
            "Fast LLM config",
            fast_llm_config.model_dump_json(exclude_none=True),
            debug_type=DebugType.LLM_CONFIG,
        )
        fast_client = create_llm_client(fast_llm_config)

    compact_client: LLMClientABC | None = None
    selected_compact_model = config.get_first_available_model(config.compact_model)
    if selected_compact_model is not None:
        compact_llm_config = config.get_model_config(selected_compact_model)
        log_debug(
            "Compact LLM config",
            compact_llm_config.model_dump_json(exclude_none=True),
            debug_type=DebugType.LLM_CONFIG,
        )
        compact_client = create_llm_client(compact_llm_config)

    if skip_sub_agents:
        return LLMClients(main=main_client, main_model_alias=model_name, fast=fast_client, compact=compact_client)

    helper = SubAgentModelResolver(config)
    sub_agent_candidates = helper.build_sub_agent_client_candidates()
    user_sub_agent_models = config.get_user_sub_agent_models()
    for model_pref in user_sub_agent_models.values():
        if not config.iter_model_config_candidates(model_pref):
            _ = config.get_first_available_model(model_pref)

    sub_clients: dict[SubAgentType, LLMClientABC] = {}
    for sub_agent_type, candidates in sub_agent_candidates.items():
        try:
            sub_clients[sub_agent_type] = FallbackLLMClient(candidates)
        except ValueError:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.name
            if role_key in user_sub_agent_models:
                raise
            log_debug(
                f"Sub-agent '{sub_agent_type}' builtin models not available, falling back to main model",
                debug_type=DebugType.LLM_CONFIG,
            )

    return LLMClients(
        main=main_client,
        main_model_alias=model_name,
        sub_clients=sub_clients,
        fast=fast_client,
        compact=compact_client,
    )


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
