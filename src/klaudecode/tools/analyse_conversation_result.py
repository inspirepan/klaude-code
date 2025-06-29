from pydantic import BaseModel, Field

from ..tool import Tool


class AnalyzeConversationTool(Tool):
    name = 'AnalyzeConversationResult'
    desc = 'Return the result of your analysis of the conversation history'

    class Input(BaseModel):
        command_name: str = Field(description='Short, descriptive name for the command (lowercase, use underscores)')
        description: str = Field(description='Brief description of what this command does')
        content: str = Field(description='The command content with $ARGUMENTS placeholder where user input should be substituted')

    async def run(self, agent, **kwargs) -> str:
        pass
