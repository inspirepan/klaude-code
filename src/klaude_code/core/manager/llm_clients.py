"""Container for main and sub-agent LLM clients."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import tools
from klaude_code.protocol.tools import SubAgentType


def _default_sub_clients() -> dict[SubAgentType, LLMClientABC]:
    return {}


@dataclass
class LLMClients:
    """Container for LLM clients used by main agent and sub-agents."""

    main: LLMClientABC
    main_model_alias: str = ""
    sub_clients: dict[SubAgentType, LLMClientABC] = dataclass_field(default_factory=_default_sub_clients)
    compact: LLMClientABC | None = None

    def get_client(self, sub_agent_type: SubAgentType | None = None) -> LLMClientABC:
        """Return client for a sub-agent type or the main client."""

        if sub_agent_type is None:
            return self.main
        client = self.sub_clients.get(sub_agent_type)
        if client is not None:
            return client
        if sub_agent_type != tools.TASK:
            fallback = self.sub_clients.get(tools.TASK)
            if fallback is not None:
                return fallback
        return self.main

    def get_compact_client(self) -> LLMClientABC:
        """Return compact client if configured, otherwise main client."""
        return self.compact or self.main
