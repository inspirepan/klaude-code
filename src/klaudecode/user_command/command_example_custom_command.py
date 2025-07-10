from typing import Generator

from rich.abc import RichRenderable
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..agent import AgentState
from ..message import UserMessage
from ..prompt.commands import GIT_COMMIT_COMMAND
from ..tui import ColorStyle, render_grid
from ..user_input import Command, CommandHandleOutput, UserInput, user_select
from .custom_command_manager import CustomCommandManager


class ExampleCustomCommand(Command):
    def get_name(self) -> str:
        return 'example_custom_command'

    def get_command_desc(self) -> str:
        return 'Create example custom command'

    @classmethod
    def already_has_custom_command(cls) -> bool:
        return CustomCommandManager.project_commands_dir().exists() or CustomCommandManager.user_commands_dir().exists()

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.removed = True

        scope_options = ['User commands (~/.claude/commands/)', 'Project commands (.claude/commands/)']
        selected_idx = await user_select(scope_options, 'Select where to create the example command:')

        if selected_idx is not None:
            if selected_idx == 0:
                # User commands
                commands_dir = CustomCommandManager.user_commands_dir()
                scope_info = 'user'
            else:
                # Project commands
                commands_dir = CustomCommandManager.project_commands_dir(agent_state.session.work_dir)
                scope_info = 'project'

            # Create directory if it doesn't exist
            commands_dir.mkdir(parents=True, exist_ok=True)

            # Create the git commit example command
            git_commit_file = commands_dir / 'create_git_commit.md'
            git_commit_content = GIT_COMMIT_COMMAND

            with open(git_commit_file, 'w', encoding='utf-8') as f:
                f.write(git_commit_content)

            command_handle_output.user_msg.set_extra_data('git_commit_file', str(git_commit_file))
            command_handle_output.user_msg.set_extra_data('scope', scope_info)

        return command_handle_output

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        git_commit_file = user_msg.get_extra_data('git_commit_file')
        scope = user_msg.get_extra_data('scope')
        if git_commit_file:
            yield Panel.fit(
                Group(
                    Text.assemble(('✓ ', ColorStyle.SUCCESS.bold), (f'Example commands created in {scope} scope:', ColorStyle.SUCCESS), (' (restart to use)', ColorStyle.HINT)),
                    '',
                    render_grid(
                        [
                            [Text('/create_git_commit ', style=ColorStyle.SUCCESS.bold), Text(git_commit_file)],
                        ]
                    ),
                ),
                border_style=ColorStyle.SUCCESS,
            )
