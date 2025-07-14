import os
from datetime import datetime
from typing import Generator

from rich.abc import RichRenderable
from rich.text import Text

from ..agent import AgentState
from ..message import AIMessage, ToolMessage, UserMessage
from ..tui import ColorStyle, render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput


class OutputCommand(Command):
    def get_name(self) -> str:
        return 'output'

    def get_command_desc(self) -> str:
        return 'Generate a markdown file output of current session'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.need_agent_run = False

        output_dir = agent_state.session.work_dir / '.klaude' / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'output_{timestamp}.md'

        markdown_content = self._generate_markdown_content(agent_state)

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
        except Exception as e:
            error_msg = f'Failed to write file: {e}'
            command_handle_output.user_msg.set_extra_data('error_msg', error_msg)
            return command_handle_output

        try:
            if os.name == 'posix':
                os.system(f'open "{output_file}"')
            elif os.name == 'nt':
                os.system(f'start "" "{output_file}"')
        except Exception as e:
            error_msg = f'Failed to open file: {e}'
            command_handle_output.user_msg.set_extra_data('error_msg', error_msg)
            return command_handle_output

        command_handle_output.user_msg.set_extra_data('output_file', str(output_file))
        command_handle_output.user_msg.set_extra_data('content_length', len(markdown_content))

        return command_handle_output

    def _generate_markdown_content(self, agent_state: 'AgentState') -> str:
        """Generate markdown content with conversation sections based on user-AI message pairs"""
        content_parts = []
        all_messages = agent_state.session.messages.messages
        task_sections = self._extract_task_sections(all_messages)
        content_parts.extend(task_sections)

        conversation_sections = self._extract_conversation_sections(all_messages)
        content_parts.extend(conversation_sections)

        return '\n\n'.join(content_parts)

    def _extract_conversation_sections(self, all_messages: list) -> list[str]:
        """Extract conversation sections: user message + AI response + Task tools in between"""
        sections = []

        user_messages = []
        for i, msg in enumerate(all_messages):
            if isinstance(msg, UserMessage) and msg.content.strip():
                user_messages.append((i, msg))

        if not user_messages:
            return sections

        for i, (user_idx, user_msg) in enumerate(user_messages):
            # Find the range for this conversation section
            start_idx = user_idx
            end_idx = user_messages[i + 1][0] if i + 1 < len(user_messages) else len(all_messages)

            # Find the last AI message with content in this range
            last_ai_msg = None
            for j in range(end_idx - 1, start_idx, -1):
                msg = all_messages[j]
                if isinstance(msg, AIMessage) and msg.content.strip():
                    last_ai_msg = msg
                    break

            if not last_ai_msg:
                continue

            # Extract Task tools in this conversation section
            section_parts = []

            # Add user message as title and AI response
            section_parts.append(f'# User: {user_msg.content.strip()}\n\n{last_ai_msg.content}')

            sections.append('\n\n'.join(section_parts))

        return sections

    def _extract_task_sections(self, all_messages: list) -> list[str]:
        """Extract Task tool calls and their results within a specific message range"""
        task_sections = []

        for msg in all_messages:
            if isinstance(msg, ToolMessage) and msg.tool_call.tool_name == 'Task':
                description = msg.tool_call.tool_args_dict.get('description', 'Task')
                section = f'# Task: {description}\n\n{msg.content}'
                task_sections.append(section)

        return task_sections

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        error_msg = user_msg.get_extra_data('error_msg')
        if error_msg:
            yield render_suffix(Text.assemble('Error: ', Text(error_msg, style=ColorStyle.ERROR)))
            return

        output_file = user_msg.get_extra_data('output_file')
        content_length = user_msg.get_extra_data('content_length')

        if output_file and content_length:
            yield render_suffix(Text.assemble('File: ', Text(output_file, style=ColorStyle.HIGHLIGHT)))
            yield render_suffix(Text.assemble('Content length: ', Text(str(content_length), style=ColorStyle.HIGHLIGHT)))
