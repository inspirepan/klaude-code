from pathlib import Path
from typing import Generator

from rich.abc import RichRenderable
from rich.text import Text

from ..agent import AgentState
from ..message import UserMessage
from ..tui import ColorStyle, get_prompt_toolkit_color, render_suffix
from ..user_input import CommandHandleOutput, InputModeCommand, UserInput, user_select


class MemoryMode(InputModeCommand):
    def get_name(self) -> str:
        return 'memory_input'

    def _get_prompt(self) -> str:
        return '#'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.MEMORY_MODE)

    def _get_placeholder(self) -> str:
        return 'Add to memory...'

    def binding_key(self) -> str:
        return '#'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        content = user_input.cleaned_input
        command_handle_output.need_agent_run = False

        if not content.strip():
            command_handle_output.user_msg.set_extra_data('result', 'No content to save')
            command_handle_output.user_msg.set_extra_data('status', 'error')
            return command_handle_output

        options = ['Project memory          Checked in at ./CLAUDE.md', 'User memory             Saved in ~/.claude/CLAUDE.md']

        choice = await user_select(options, 'Where should this memory be saved?')

        if choice is None:
            command_handle_output.user_msg.set_extra_data('result', 'Cancelled by user')
            command_handle_output.user_msg.set_extra_data('status', 'cancelled')
            return command_handle_output

        if choice == 0:
            claude_md_path = Path(agent_state.session.work_dir) / 'CLAUDE.md'
            location = 'project'
        else:
            claude_md_path = Path.home() / '.claude' / 'CLAUDE.md'
            claude_md_path.parent.mkdir(exist_ok=True)
            location = 'system'

        lines = [line.strip() for line in content.split('\n') if line.strip()]
        formatted_content = '\n'.join(f'- {line}' for line in lines)

        if claude_md_path.exists():
            existing_content = claude_md_path.read_text(encoding='utf-8')
            new_content = f'{existing_content}\n\n{formatted_content}'
        else:
            new_content = formatted_content

        claude_md_path.write_text(new_content, encoding='utf-8')

        command_handle_output.user_msg.set_extra_data('result', f'Saved to {claude_md_path}')
        command_handle_output.user_msg.set_extra_data('status', 'success')
        command_handle_output.user_msg.set_extra_data('location', location)
        command_handle_output.user_msg.set_extra_data('path', str(claude_md_path))
        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        result = user_msg.get_extra_data('result', '')
        status = user_msg.get_extra_data('status', '')

        if result:
            if status == 'success':
                yield render_suffix(Text(result, style=ColorStyle.MEMORY_MODE))
            elif status == 'error':
                yield render_suffix(Text(result, style=ColorStyle.ERROR.bold))
            else:
                yield render_suffix(result)
