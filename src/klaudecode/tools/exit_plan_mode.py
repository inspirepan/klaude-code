from typing import Annotated

from pydantic import BaseModel, Field
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from ..message import ToolCall, ToolMessage, register_tool_call_renderer, register_tool_result_renderer
from ..prompt.plan_mode import APPROVE_HINT, EXIT_PLAN_MODE_TOOL_DESC, EXIT_PLAN_MODE_TOOL_PLAN_ARG_DESC, REJECT_HINT
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle, render_markdown, render_suffix

"""
- Interactive plan approval workflow with rich UI rendering
- Markdown-formatted plan display with syntax highlighting
- User approval/rejection handling and visual feedback
- Special tool handler bypass for agent-level interception
"""


class ExitPlanModeTool(Tool):
    name = 'exit_plan_mode'
    desc = EXIT_PLAN_MODE_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        plan: Annotated[str, Field(description=EXIT_PLAN_MODE_TOOL_PLAN_ARG_DESC)]

    @classmethod
    def skip_in_tool_handler(cls) -> bool:
        return True

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        # This should never be called as the tool is intercepted in agent.py
        pass


@register_tool_call_renderer(ExitPlanModeTool.name)
def render_exit_plan_mode_args(tool_call: ToolCall, is_suffix: bool = False):
    yield Text("Here is Claude's plan:", ColorStyle.TOOL_NAME.bold)
    yield Padding.indent(
        Panel.fit(render_markdown(tool_call.tool_args_dict['plan']), border_style=ColorStyle.LINE),
        level=2,
    )


@register_tool_result_renderer(ExitPlanModeTool.name)
def render_exit_plan_mode_content(tool_msg: ToolMessage):
    approved = tool_msg.get_extra_data('approved', False)
    yield render_suffix(APPROVE_HINT if approved else REJECT_HINT, style=ColorStyle.SUCCESS if approved else ColorStyle.ERROR)
