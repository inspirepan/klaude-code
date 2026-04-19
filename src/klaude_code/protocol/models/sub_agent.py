from pydantic import BaseModel

from klaude_code.protocol.tools import SubAgentType


class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str
    fork_context: bool = False

__all__ = ["SubAgentState"]