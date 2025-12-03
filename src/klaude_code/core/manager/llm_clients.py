"""Container for main and sub-agent LLM clients."""

from __future__ import annotations

from collections.abc import Callable

from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import llm_param
from klaude_code.protocol.tools import SubAgentType


class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    def __init__(
        self,
        main_factory: Callable[[], LLMClientABC],
        main_model_name: str,
        main_llm_config: llm_param.LLMConfigParameter,
    ) -> None:
        self._main_factory: Callable[[], LLMClientABC] | None = main_factory
        self._main_client: LLMClientABC | None = None
        self._main_model_name: str = main_model_name
        self._main_llm_config: llm_param.LLMConfigParameter = main_llm_config
        self._sub_clients: dict[SubAgentType, LLMClientABC] = {}
        self._sub_factories: dict[SubAgentType, Callable[[], LLMClientABC]] = {}

    @property
    def main_model_name(self) -> str:
        return self._main_model_name

    def get_llm_config(self) -> llm_param.LLMConfigParameter:
        return self._main_llm_config

    @property
    def main(self) -> LLMClientABC:
        if self._main_client is None:
            if self._main_factory is None:
                raise RuntimeError("Main client factory not set")
            self._main_client = self._main_factory()
            self._main_factory = None
        return self._main_client

    def register_sub_client_factory(
        self,
        sub_agent_type: SubAgentType,
        factory: Callable[[], LLMClientABC],
    ) -> None:
        self._sub_factories[sub_agent_type] = factory

    def get_client(self, sub_agent_type: SubAgentType | None = None) -> LLMClientABC:
        """Return client for a sub-agent type or the main client."""

        if sub_agent_type is None:
            return self.main

        existing = self._sub_clients.get(sub_agent_type)
        if existing is not None:
            return existing

        factory = self._sub_factories.get(sub_agent_type)
        if factory is None:
            return self.main

        client = factory()
        self._sub_clients[sub_agent_type] = client
        return client
