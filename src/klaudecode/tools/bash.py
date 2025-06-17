import json
from typing import Annotated, Optional

from pydantic import BaseModel, Field
from rich.live import Live

from ..message import ToolCallMessage, ToolMessage
from ..tool import Tool, tool_input


class BashTool(Tool):
    name = "Bash"
    desc = "Execute a bash command"

    @tool_input
    class Input(BaseModel):
        command: Annotated[str, Field(description="The bash command to execute")]
        description: Annotated[Optional[str], Field(description="Description of what this command does")] = None
        timeout: Annotated[Optional[int], Field(description="Optional timeout in milliseconds (max 600000)")] = None

    def bash(input: Input) -> str:
        print("bash")

    def parse_args(self, tool_call: ToolCallMessage) -> Input:
        args_dict = json.loads(tool_call.function_arguments)
        return self.InputModel(**args_dict)

    def update_output(self, output: str, tool_msg: ToolMessage, live: Optional[Live]):
        _ = output, tool_msg, live
