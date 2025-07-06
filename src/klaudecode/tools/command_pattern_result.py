from typing import Annotated

from pydantic import BaseModel, Field

from ..tool import Tool


class CommandPatternResultTool(Tool):
    name = 'CommandPatternResult'
    desc = 'Return the command pattern result of your analysis of the conversation history'

    class Input(BaseModel):
        command_name: Annotated[str, Field(description='Short, descriptive name for the command (lowercase, use underscores)')]
        description: Annotated[str, Field(description='Brief description of what this command does')]
        content: Annotated[str, Field(description='The command content with $ARGUMENTS placeholder where user input should be substituted')]
