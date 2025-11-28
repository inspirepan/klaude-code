from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, TypeVar

from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol.llm_parameter import LLMClientProtocol, LLMConfigParameter
from klaude_code.protocol.tools import SubAgentType
from klaude_code.trace import DebugType, log_debug

if TYPE_CHECKING:
    from klaude_code.config.config import Config

_REGISTRY: dict[LLMClientProtocol, type[LLMClientABC]] = {}

T = TypeVar("T", bound=LLMClientABC)


def register(name: LLMClientProtocol) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def create_llm_client(config: LLMConfigParameter) -> LLMClientABC:
    if config.protocol not in _REGISTRY:
        raise ValueError(f"Unknown LLMClient protocol: {config.protocol}")
    return _REGISTRY[config.protocol].create(config)


@dataclass
class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    main: LLMClientABC
    sub_clients: dict[SubAgentType, LLMClientABC] = field(default_factory=lambda: {})

    def get_client(self, sub_agent_type: SubAgentType | None = None) -> LLMClientABC:
        """Get client for given sub-agent type, or main client if None."""
        if sub_agent_type is None:
            return self.main
        return self.sub_clients.get(sub_agent_type) or self.main

    @classmethod
    def from_config(
        cls,
        config: Config,
        model_override: str | None = None,
        enabled_sub_agents: list[SubAgentType] | None = None,
    ) -> LLMClients:
        """Create LLMClients from application config.

        Args:
            config: Application configuration
            model_override: Optional model name to override the main model
            enabled_sub_agents: List of sub-agent types to initialize clients for

        Returns:
            LLMClients instance
        """
        from klaude_code.core.sub_agent import get_sub_agent_profile

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

        main_client = create_llm_client(llm_config)
        sub_clients: dict[SubAgentType, LLMClientABC] = {}

        # Initialize sub-agent clients
        for sub_agent_type in enabled_sub_agents or []:
            model_name = config.subagent_models.get(sub_agent_type)
            if not model_name:
                continue
            profile = get_sub_agent_profile(sub_agent_type)
            if not profile.enabled_for_model(main_client.model_name):
                continue
            sub_llm_config = config.get_model_config(model_name)
            sub_clients[sub_agent_type] = create_llm_client(sub_llm_config)

        return cls(main=main_client, sub_clients=sub_clients)
