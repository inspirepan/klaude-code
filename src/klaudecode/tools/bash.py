from typing import Annotated, Optional

from pydantic import BaseModel, Field

from ..message import ToolCallMessage, ToolMessage
from ..tool import Tool, ToolInstance


class BashTool(Tool):
    name = "Bash"
    desc = "Execute a bash command"

    class Input(BaseModel):
        command: Annotated[str, Field(description="The bash command to execute")]
        description: Annotated[Optional[str], Field(description="Description of what this command does")] = None
        timeout: Annotated[Optional[int], Field(description="Optional timeout in milliseconds (max 600000)")] = None

    @classmethod
    def invoke(cls, tool_call: ToolCallMessage, instance: 'ToolInstance') -> ToolMessage:
        args: "BashTool.Input" = cls.parse_input_args(tool_call)
        instance.get_tool_message().content = "EXE: " + args.command
        return
