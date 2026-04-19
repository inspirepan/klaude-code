"""LLM client containers and factory functions."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from klaude_code.config import Config
from klaude_code.config.sub_agent_model import SubAgentModelResolver
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType


def _default_sub_clients() -> dict[SubAgentType, LLMClientABC]:
    return {}


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
    model_name = model_override or config.main_model
    if model_name is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    llm_config = config.get_model_config(model_name)

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)

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
    sub_agent_configs = helper.build_sub_agent_client_configs()
    user_sub_agent_models = config.get_user_sub_agent_models()

    sub_clients: dict[SubAgentType, LLMClientABC] = {}
    for sub_agent_type, sub_model_name in sub_agent_configs.items():
        try:
            sub_llm_config = config.get_model_config(sub_model_name)
            sub_clients[sub_agent_type] = create_llm_client(sub_llm_config)
        except ValueError:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.name
            if role_key in user_sub_agent_models:
                raise
            log_debug(
                f"Sub-agent '{sub_agent_type}' builtin model '{sub_model_name}' not available, falling back to main model",
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
