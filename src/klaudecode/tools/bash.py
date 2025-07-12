from typing import Annotated

from pydantic import BaseModel, Field
from rich.columns import Columns
from rich.console import Group
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from ..message import ToolCall, register_tool_call_renderer
from ..prompt.tools import BASH_TOOL_DESC
from ..tool import Tool, ToolInstance
from ..tui import ColorStyle
from ..utils.bash_utils.command_execution import BashCommandExecutor
from ..utils.bash_utils.security import BashSecurity

"""
- Cross-platform command execution with real-time output streaming
- Advanced security validation and dangerous command blocking
- Interactive prompt detection and timeout management
- Process tree cleanup and signal handling for graceful termination

Output Truncation Logic:
- Truncation triggers when output ≥ 30,000 chars AND ≥ 400 lines
- Preserves first 200 lines (command start, parameters, early output)
- Preserves last 200 lines (command end, results, exit codes)
- Middle content is truncated with summary: [... X lines (Y chars) truncated from middle ...]
- Ensures important command completion info is never lost
"""


class BashTool(Tool):
    name = 'Bash'
    desc = BASH_TOOL_DESC
    parallelable: bool = False

    class Input(BaseModel):
        command: Annotated[str, Field(description='The command to execute')]
        description: Annotated[
            str,
            Field(
                description="""Clear, concise description of what this command does in 5-10 words. Examples:
Input: ls
Output: Lists files in current directory

Input: git status
Output: Shows working tree status

Input: npm install
Output: Installs package dependencies

Input: mkdir foo
Output: Creates directory 'foo'"""
            ),
        ] = ''
        timeout: Annotated[int, Field(description='Optional timeout in milliseconds (max 600000)')] = 0

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'BashTool.Input' = cls.parse_input_args(tool_call)

        # Validate command safety
        is_safe, validation_msg = BashSecurity.validate_command_safety(args.command)
        if not is_safe:
            instance.tool_result().set_error_msg(validation_msg)
            return
        if '<system-reminder>' in validation_msg:
            instance.tool_result().append_post_system_reminder(validation_msg)

        # Set timeout
        timeout_ms = args.timeout if args.timeout > 0 else BashCommandExecutor.DEFAULT_TIMEOUT
        if timeout_ms > BashCommandExecutor.MAX_TIMEOUT:
            timeout_ms = BashCommandExecutor.MAX_TIMEOUT
        timeout_seconds = timeout_ms / 1000.0

        # Define callbacks for the execution function
        def check_canceled():
            return instance.tool_result().tool_call.status == 'canceled' or instance.check_interrupt()

        def update_content(content: str):
            instance.tool_result().set_content(content.strip())

        # Execute the command using the abstracted function
        error_msg = BashCommandExecutor.execute_bash_command(command=args.command, timeout_seconds=timeout_seconds, check_canceled=check_canceled, update_content=update_content)

        # Handle any error returned from execution
        if error_msg:
            instance.tool_result().set_error_msg(error_msg)


@register_tool_call_renderer(BashTool.name)
def render_bash_args(tool_call: ToolCall, is_suffix: bool = False):
    command = tool_call.tool_args_dict.get('command', '')
    if is_suffix:
        yield Text.assemble(('Bash', ColorStyle.MAIN.bold), '(', command, ')')
        return

    description = tool_call.tool_args_dict.get('description', '')

    is_multiline = '\n' in command
    is_long = len(command) > 20

    if is_multiline or is_long:
        yield Text.assemble(('Bash', ColorStyle.TOOL_NAME.bold), '(', (description, ColorStyle.TOOL_NAME.bold), ') → ')
        yield Padding.indent(Group(Rule(style=ColorStyle.LINE), Text(command), Rule(style=ColorStyle.LINE)), level=2)
    else:
        yield Columns([Text.assemble(('Bash', ColorStyle.TOOL_NAME.bold)), Text.assemble('(', Text(command), ')')], padding=(0, 0))
