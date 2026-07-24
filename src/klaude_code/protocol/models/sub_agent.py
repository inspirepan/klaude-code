from pydantic import BaseModel

from klaude_code.protocol.tools import SubAgentType


class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str
    model: str | None = None
    fork_context: bool = False
    parent_tool_batch_id: str | None = None
    parent_tool_batch_index: int | None = None
    parent_tool_batch_size: int | None = None


__all__ = ["SubAgentState"]
