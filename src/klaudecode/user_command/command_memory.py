import subprocess
from pathlib import Path
from typing import Generator

from rich.abc import RichRenderable

from ..agent import AgentState
from ..message import UserMessage
from ..tui import render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput, user_select


class MemoryCommand(Command):
    def get_name(self) -> str:
        return 'memory'

    def get_command_desc(self) -> str:
        return 'Edit Claude memory files'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.removed = True

        options = ['Project memory          ./CLAUDE.md', 'User memory             ~/.claude/CLAUDE.md']

        selected_idx = await user_select(options, 'Which memory file to open?')

        if selected_idx is None:
            command_handle_output.user_msg.set_extra_data('memory_cancelled', True)
            return command_handle_output

        if selected_idx == 0:
            memory_path = Path.cwd() / 'CLAUDE.md'
            command_handle_output.user_msg.set_extra_data('scope', 'project')
        else:
            memory_path = Path.home() / '.claude' / 'CLAUDE.md'
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            command_handle_output.user_msg.set_extra_data('scope', 'user')
        try:
            subprocess.run(['open', str(memory_path)], check=True)
            command_handle_output.user_msg.set_extra_data('memory_opened', str(memory_path))
        except subprocess.CalledProcessError:
            try:
                subprocess.run(['code', str(memory_path)], check=True)
                command_handle_output.user_msg.set_extra_data('memory_opened', str(memory_path))
            except subprocess.CalledProcessError:
                try:
                    subprocess.run(['vim', str(memory_path)], check=True)
                    command_handle_output.user_msg.set_extra_data('memory_opened', str(memory_path))
                except subprocess.CalledProcessError:
                    command_handle_output.user_msg.set_extra_data('memory_error', str(memory_path))

        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        memory_opened = user_msg.get_extra_data('memory_opened')
        memory_error = user_msg.get_extra_data('memory_error')
        memory_cancelled = user_msg.get_extra_data('memory_cancelled')
        memory_scope = user_msg.get_extra_data('scope', '')

        if memory_opened:
            yield render_suffix(f'Opened {memory_scope} memory at {memory_opened}')
        elif memory_error:
            yield render_suffix(f'Failed to open {memory_scope} memory at {memory_error}')
        elif memory_cancelled:
            yield render_suffix('Cancelled by user')
