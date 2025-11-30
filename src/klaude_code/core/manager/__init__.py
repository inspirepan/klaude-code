"""Core runtime and state management components.

Expose the manager layer via package imports to reduce module churn in
callers. This keeps long-lived runtime state helpers (agents, tasks,
LLM clients, sub-agents) distinct from per-session execution logic in
``klaude_code.core``.
"""

from klaude_code.core.manager.agent_manager import AgentManager
from klaude_code.core.manager.llm_clients import LLMClients
from klaude_code.core.manager.llm_clients_builder import build_llm_clients
from klaude_code.core.manager.sub_agent_manager import SubAgentManager

__all__ = [
    "AgentManager",
    "LLMClients",
    "SubAgentManager",
    "build_llm_clients",
]
