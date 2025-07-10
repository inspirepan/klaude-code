import json
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel

from ..message import ToolCall
from .executor import ToolExecutor
from .schema import ToolSchema

if TYPE_CHECKING:
    from ..agent import AgentState
    from .instance import ToolInstance


class Tool(ABC):
    """
    Tool is the base class for all tools.
    """

    name: str = ''
    desc: str = ''
    parallelable: bool = True
    timeout = 300

    @classmethod
    def get_name(cls) -> str:
        return cls.name

    @classmethod
    def get_desc(cls) -> str:
        return cls.desc

    @classmethod
    def is_parallelable(cls) -> bool:
        return cls.parallelable

    @classmethod
    def get_timeout(cls) -> float:
        return cls.timeout

    @classmethod
    def skip_in_tool_handler(cls) -> bool:
        return False

    @classmethod
    def get_parameters(cls) -> Dict[str, Any]:
        """Get tool parameters schema."""
        return ToolSchema.get_parameters(cls)

    @classmethod
    def tokens(cls) -> int:
        """Calculate total tokens for tool description and parameters."""
        return ToolSchema.calculate_tokens(cls)

    @classmethod
    def openai_schema(cls) -> Dict[str, Any]:
        """Generate OpenAI compatible schema."""
        return ToolSchema.openai_schema(cls)

    @classmethod
    def anthropic_schema(cls) -> Dict[str, Any]:
        """Generate Anthropic compatible schema."""
        return ToolSchema.anthropic_schema(cls)

    def __str__(self) -> str:
        return self.json_openai_schema()

    def __repr__(self) -> str:
        return self.json_openai_schema()

    @classmethod
    def json_openai_schema(cls):
        return json.dumps(cls.openai_schema())

    @classmethod
    def create_instance(cls, tool_call: ToolCall, agent_state: 'AgentState') -> 'ToolInstance':
        from .instance import ToolInstance

        return ToolInstance(tool=cls, tool_call=tool_call, agent_state=agent_state)

    @classmethod
    def parse_input_args(cls, tool_call: ToolCall) -> Optional[BaseModel]:
        if hasattr(cls, 'Input') and issubclass(cls.Input, BaseModel):
            args_dict = json.loads(tool_call.tool_args)
            input_inst = cls.Input(**args_dict)
            return input_inst
        return None

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        raise NotImplementedError

    @classmethod
    async def invoke_async(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        """Execute tool asynchronously with proper error handling."""
        await ToolExecutor.execute_async(cls, tool_call, instance)
