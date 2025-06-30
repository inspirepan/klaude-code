from pathlib import Path
from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..message import UserMessage
from ..tui import ColorStyle, console, render_grid, render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput, user_select
from ..utils.str_utils import sanitize_filename

if TYPE_CHECKING:
    from ..agent import Agent


class SaveCustomCommandCommand(Command):
    def get_name(self) -> str:
        return 'save_custom_command'

    def get_command_desc(self) -> str:
        return 'Analyze current conversation pattern and save a reusable custom command'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)

        console.print()
        analysis_result = await agent.session.analyze_conversation_for_command(llm_manager=agent.llm_manager)

        if not analysis_result:
            console.print('Failed to analyze conversation for command creation', style=ColorStyle.ERROR.value)
            return command_handle_output

        command_name = analysis_result.get('command_name', 'untitled_command')
        description = analysis_result.get('description', 'Custom command')
        content = analysis_result.get('content', '')

        command_name = sanitize_filename(command_name)
        if not command_name:
            command_name = 'untitled_command'

        console.print()
        console.print(
            Panel.fit(
                Group(
                    Text('Generated Command:', ColorStyle.HIGHLIGHT.bold()),
                    render_grid(
                        [
                            [
                                Text('Name:', ColorStyle.INFO.bold()),
                                Text(command_name),
                            ],
                            [
                                Text('Description:', ColorStyle.INFO.bold()),
                                Text(description),
                            ],
                            [
                                Text('Content:', ColorStyle.INFO.bold()),
                                Text(content),
                            ],
                        ]
                    ),
                ),
                border_style=ColorStyle.AGENT_BORDER.value,
            )
        )
        console.print()

        options = ['Save as project command (.claude/commands/)', 'Save as user command (~/.claude/commands/)', 'Reject this command']

        selected_idx = await user_select(options, 'What would you like to do?')

        if selected_idx is None or selected_idx == 2:
            return command_handle_output

        if selected_idx == 0:
            commands_dir = Path.cwd() / '.claude' / 'commands'
            scope = 'project'
        else:
            commands_dir = Path.home() / '.claude' / 'commands'
            scope = 'user'

        commands_dir.mkdir(parents=True, exist_ok=True)

        command_file = commands_dir / f'{command_name}.md'
        counter = 1
        while command_file.exists():
            command_file = commands_dir / f'{command_name}_{counter}.md'
            counter += 1

        command_content = f"""---
description: {description}
---

{content}
"""

        try:
            with open(command_file, 'w', encoding='utf-8') as f:
                f.write(command_content)

            command_handle_output.user_msg.set_extra_data('command_saved', {'name': command_name, 'path': str(command_file), 'scope': scope})

        except Exception as e:
            console.print(f'Failed to save command: {e}', style=ColorStyle.ERROR.value)

        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        command_saved = user_msg.get_extra_data('command_saved')
        if command_saved:
            yield render_suffix(
                Text.assemble(
                    'Command ',
                    (f'{command_saved["name"]}', 'bold'),
                    ' saved as ',
                    f'{command_saved["scope"]}',
                    ' command at ',
                    f'{command_saved["path"]}',
                    style=ColorStyle.SUCCESS.value,
                )
            )
        else:
            yield render_suffix('Command not saved')
