from typing import List, Optional

from ..config import ConfigModel
from ..llm import LLMManager
from ..mcp.mcp_tool import MCPManager
from ..message import AgentUsage
from ..session import Session
from ..tool import Tool


class AgentState:
    """
    AgentState contains all the state data.
    This includes session, config, managers, and other stateful components.
    """

    def __init__(
        self,
        session: Session,
        config: Optional[ConfigModel] = None,
        available_tools: Optional[List[Tool]] = None,
        print_switch: bool = True,
    ):
        # Core state
        self.session: Session = session
        self.config: Optional[ConfigModel] = config
        self.print_switch = print_switch

        # Plan Mode state
        self.plan_mode_activated: bool = False

        # Tools state
        self.available_tools = available_tools or []
        self._cached_all_tools: Optional[List[Tool]] = None
        self._tools_cache_dirty: bool = True

        # Managers
        self.llm_manager: Optional[LLMManager] = None
        self.mcp_manager: Optional[MCPManager] = None

        # Usage tracking
        self.usage = AgentUsage()

    def initialize_llm(self):
        """Initialize LLM manager if not already initialized."""
        if not self.llm_manager:
            self.llm_manager = LLMManager()
        self.llm_manager.initialize_from_config(self.config)

    async def initialize_mcp(self) -> bool:
        """Initialize MCP manager"""
        if self.mcp_manager is None:
            self.mcp_manager = MCPManager(self.session.work_dir)
            result = await self.mcp_manager.initialize()
            self.invalidate_tools_cache()
            return result
        return True

    @property
    def all_tools(self) -> List[Tool]:
        """Get all available tools including MCP tools with caching"""
        if not self._tools_cache_dirty and self._cached_all_tools is not None:
            return self._cached_all_tools

        tools = list(self.available_tools) if self.available_tools else []

        if self.mcp_manager and self.mcp_manager.is_initialized():
            mcp_tools = self.mcp_manager.get_mcp_tools()
            tools.extend(mcp_tools)

        self._cached_all_tools = tools
        self._tools_cache_dirty = False
        return tools

    def invalidate_tools_cache(self):
        """Invalidate the tools cache to force refresh on next get_all_tools call"""
        self._tools_cache_dirty = True

    def print_usage(self):
        """Print usage statistics"""
        from ..tui import console

        console.print()
        console.print(self.usage)
