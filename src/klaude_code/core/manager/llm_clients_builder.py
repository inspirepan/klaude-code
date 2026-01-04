"""Factory helpers for building :class:`LLMClients` from config."""

from __future__ import annotations

from klaude_code.config import Config
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol.sub_agent import AVAILABILITY_IMAGE_MODEL, iter_sub_agent_profiles
from klaude_code.protocol.tools import SubAgentType


def _resolve_model_for_requirement(requirement: str | None, config: Config) -> str | None:
    """Resolve the model name for a given availability requirement.

    Args:
        requirement: The availability requirement constant.
        config: The config to use for model lookup.

    Returns:
        The model name if found, None otherwise.
    """
    if requirement == AVAILABILITY_IMAGE_MODEL:
        return config.get_first_available_image_model()
    return None


def build_llm_clients(
    config: Config,
    *,
    model_override: str | None = None,
    skip_sub_agents: bool = False,
) -> LLMClients:
    """Create an ``LLMClients`` bundle driven by application config.

    Args:
        config: Application configuration.
        model_override: Override for the main model name.
        skip_sub_agents: If True, skip initializing sub-agent clients (e.g., for vanilla/banana modes).
    """

    # Resolve main agent LLM config
    model_name = model_override or config.main_model
    if model_name is None:
        raise ValueError("No model specified. Set main_model in the config or pass --model.")
    llm_config = config.get_model_config(model_name)

    log_debug(
        "Main LLM config",
        llm_config.model_dump_json(exclude_none=True),
        style="yellow",
        debug_type=DebugType.LLM_CONFIG,
    )

    main_client = create_llm_client(llm_config)

    if skip_sub_agents:
        return LLMClients(main=main_client)

    sub_clients: dict[SubAgentType, LLMClientABC] = {}

    for profile in iter_sub_agent_profiles():
        if not profile.enabled_for_model(main_client.model_name):
            continue

        # Try configured model first, then fall back to requirement-based resolution
        sub_model_name = config.sub_agent_models.get(profile.name)
        if not sub_model_name and profile.availability_requirement:
            sub_model_name = _resolve_model_for_requirement(profile.availability_requirement, config)

        if not sub_model_name:
            continue

        sub_llm_config = config.get_model_config(sub_model_name)
        sub_clients[profile.name] = create_llm_client(sub_llm_config)

    return LLMClients(main=main_client, sub_clients=sub_clients)
