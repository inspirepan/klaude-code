"""Factory helpers for building :class:`LLMClients` from config."""

from __future__ import annotations

from klaude_code.config import Config
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.tools import SubAgentType
from klaude_code.trace import DebugType, log_debug


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    enabled_sub_agents: list[SubAgentType] | None = None,
) -> LLMClients:
    """Create an ``LLMClients`` bundle driven by application config."""

    # Resolve main agent LLM config
    if model_override:
        llm_config = config.get_model_config(model_override)
    else:
        llm_config = config.get_main_model_config()

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_model_name = str(llm_config.model)

    def _main_factory() -> LLMClientABC:
        return create_llm_client(llm_config)

    clients = LLMClients(
        main_factory=_main_factory,
        main_model_name=main_model_name,
        main_llm_config=llm_config,
    )

    for sub_agent_type in enabled_sub_agents or []:
        model_name = config.subagent_models.get(sub_agent_type)
        if not model_name:
            continue

        profile = get_sub_agent_profile(sub_agent_type)
        if not profile.enabled_for_model(main_model_name):
            continue

        def _factory(model_name_for_factory: str = model_name) -> LLMClientABC:
            sub_llm_config = config.get_model_config(model_name_for_factory)
            return create_llm_client(sub_llm_config)

        clients.register_sub_client_factory(sub_agent_type, _factory)

    return clients
