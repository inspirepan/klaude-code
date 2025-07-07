from . import user_command  # noqa: F401 # import user_command to trigger command registration
from .agent_executor import AgentExecutor
from .agent_state import AgentState
from .config import ConfigModel
from .session import Session
from .tools import BASIC_TOOLS


async def get_main_agent(session: Session, config: ConfigModel, enable_mcp: bool = False) -> AgentExecutor:
    state = AgentState(session, config, available_tools=[AgentExecutor] + BASIC_TOOLS)
    if enable_mcp:
        await state.initialize_mcp()
    return AgentExecutor(state)
