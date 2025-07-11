from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field

from ..agent.subagent import SubAgentBase
from ..prompt.system import get_subagent_system_prompt
from ..prompt.tools import TASK_TOOL_DESC
from . import BASIC_TOOLS


class TaskTool(SubAgentBase):
    """Standalone Task tool for launching sub-agents"""

    name = 'Task'
    desc = TASK_TOOL_DESC

    class Input(BaseModel):
        description: Annotated[str, Field(description='A short (3-5 word) description of the task')]
        prompt: Annotated[str, Field(description='The task for the agent to perform')]

    @classmethod
    def get_system_prompt(cls, work_dir: Path, model_name: str) -> str:
        return get_subagent_system_prompt(work_dir=work_dir, model_name=model_name)

    @classmethod
    def get_subagent_tools(cls):
        return BASIC_TOOLS
