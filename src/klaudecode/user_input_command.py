import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generator, Optional, Tuple

from rich.abc import RichRenderable
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from .config import ConfigModel
from .message import UserMessage
from .prompt.commands import INIT_COMMAND, RECENT_COMMAND, TODAY_COMMAND
from .tui import console, render_suffix
from .user_input import Command, UserInput, register_slash_command

if TYPE_CHECKING:
    from .agent import Agent

# Commands
# ---------------------

## Special Commands
# ---------------------


class StatusCommand(Command):
    def get_name(self) -> str:
        return 'status'

    def get_command_desc(self) -> str:
        return 'Show the current setup'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)
        user_msg.set_extra_data('status', agent.config)
        return user_msg, False

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        config_data = user_msg.get_extra_data('status')
        if config_data:
            if isinstance(config_data, ConfigModel):
                config_model = config_data
            elif isinstance(config_data, dict):
                config_model = ConfigModel.model_validate(config_data)
            else:
                return
            yield render_suffix(config_model)


class ContinueCommand(Command):
    def get_name(self) -> str:
        return 'continue'

    def get_command_desc(self) -> str:
        return 'Request LLM without new user message. NOTE: May cause error when no user message exists'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)
        return user_msg, True


class CompactCommand(Command):
    def get_name(self) -> str:
        return 'compact'

    def get_command_desc(self) -> str:
        return 'Clear conversation history but keep a summary in context. Optional: /compact [instructions for summarization]'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)
        user_msg.removed = True
        console.print()
        agent.append_message(user_msg, print_msg=False)
        await agent.session.compact_conversation_history(instructions=user_input.cleaned_input, show_status=True)
        return None, False

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield ''
        yield Rule(title=Text('Previous Conversation Compacted', 'bold white'), characters='=', style='white')


class CostCommand(Command):
    def get_name(self) -> str:
        return 'cost'

    def get_command_desc(self) -> str:
        return 'Show the total cost and duration of the current session'

    # TODO: Implement


class ClearCommand(Command):
    def get_name(self) -> str:
        return 'clear'

    def get_command_desc(self) -> str:
        return 'Clear conversation history and free up context'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)
        user_msg.removed = True
        user_msg.append_extra_data('cleared', True)
        agent.session.clear_conversation_history()
        return user_msg, False

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        if user_msg.get_extra_data('cleared', False):
            yield render_suffix('Conversation history cleared, context freed up')


class MacSetupCommand(Command):
    def get_name(self) -> str:
        return 'mac-setup'

    def get_command_desc(self) -> str:
        return 'Install fd and rg (ripgrep) using Homebrew on macOS for optimal performance'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)

        # Check if running on macOS
        if platform.system() != 'Darwin':
            user_msg.set_extra_data('setup_result', {'success': False, 'error': 'This command is only available on macOS'})
            return user_msg, False

        # Check if Homebrew is installed
        if not shutil.which('brew'):
            user_msg.set_extra_data('setup_result', {'success': False, 'error': 'Homebrew is not installed. Please install Homebrew first: https://brew.sh'})
            return user_msg, False

        setup_results = []

        # Check and install fd
        fd_result = self._install_tool('fd', 'Fast file finder')
        setup_results.append(fd_result)

        # Check and install rg (ripgrep)
        rg_result = self._install_tool('rg', 'Fast text search tool', package_name='ripgrep')
        setup_results.append(rg_result)

        user_msg.set_extra_data('setup_result', {'success': True, 'results': setup_results})
        return user_msg, False

    def _install_tool(self, command: str, description: str, package_name: str = None) -> dict:
        """Install a tool using Homebrew if not already installed"""
        package = package_name or command

        # Check if already installed
        if shutil.which(command):
            try:
                # Get version info
                result = subprocess.run([command, '--version'], capture_output=True, text=True, timeout=5)
                version = result.stdout.strip().split('\n')[0] if result.returncode == 0 else 'unknown'
                return {'tool': command, 'description': description, 'status': 'already_installed', 'version': version}
            except Exception:
                return {'tool': command, 'description': description, 'status': 'already_installed', 'version': 'unknown'}

        # Install using Homebrew
        try:
            result = subprocess.run(['brew', 'install', package], capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                # Get version after installation
                try:
                    version_result = subprocess.run([command, '--version'], capture_output=True, text=True, timeout=5)
                    version = version_result.stdout.strip().split('\n')[0] if version_result.returncode == 0 else 'unknown'
                except Exception:
                    version = 'installed'

                return {'tool': command, 'description': description, 'status': 'installed', 'version': version}
            else:
                return {'tool': command, 'description': description, 'status': 'failed', 'error': result.stderr.strip()}
        except subprocess.TimeoutExpired:
            return {'tool': command, 'description': description, 'status': 'failed', 'error': 'Installation timed out'}
        except Exception as e:
            return {'tool': command, 'description': description, 'status': 'failed', 'error': str(e)}

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        setup_data = user_msg.get_extra_data('setup_result')
        if not setup_data:
            return

        if not setup_data.get('success', False):
            # Show error
            error_text = Text(f'❌ {setup_data.get("error", "Unknown error")}', style='red')
            yield Panel.fit(error_text, title='Mac Setup Failed', border_style='red')
            return

        # Show results
        result_items = []
        results = setup_data.get('results', [])

        for result in results:
            tool = result['tool']
            desc = result['description']
            status = result['status']
            version = result.get('version', '')

            if status == 'already_installed':
                status_text = Text(f'✅ {tool}', style='green')
                status_text.append(f' ({desc}) - Already installed', style='dim')
                if version and version != 'unknown':
                    status_text.append(f' - {version}', style='cyan')
            elif status == 'installed':
                status_text = Text(f'🎉 {tool}', style='bright_green')
                status_text.append(f' ({desc}) - Successfully installed', style='green')
                if version and version != 'unknown':
                    status_text.append(f' - {version}', style='cyan')
            else:  # failed
                status_text = Text(f'❌ {tool}', style='red')
                status_text.append(f' ({desc}) - Failed', style='red')
                error = result.get('error', '')
                if error:
                    status_text.append(f': {error}', style='dim red')

            result_items.append(status_text)

        if result_items:
            yield Panel.fit(
                Group(*result_items), title='Mac Setup Results', border_style='green' if all(r['status'] in ['already_installed', 'installed'] for r in results) else 'yellow'
            )


## Rewrite Query Commands
# ---------------------


class RewriteQueryCommand(Command, ABC):
    @abstractmethod
    def get_query_content(self, user_input: UserInput) -> str:
        pass

    async def handle(self, agent: 'Agent', user_input: UserInput) -> Tuple[Optional[UserMessage], bool]:
        user_msg, _ = await super().handle(agent, user_input)
        user_msg.content = self.get_query_content(user_input)
        if user_input.cleaned_input:
            user_msg.content += 'Additional Instructions:\n' + user_input.cleaned_input
        return user_msg, True


class InitCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'init'

    def get_command_desc(self) -> str:
        return 'Initialize a new CLAUDE.md file with codebase documentation'

    def get_query_content(self, user_input: UserInput) -> str:
        return INIT_COMMAND


class TodayCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'today'

    def get_command_desc(self) -> str:
        return "Analyze today's development activities in this codebase through git commit history"

    def get_query_content(self, user_input: UserInput) -> str:
        return TODAY_COMMAND


class RecentCommand(RewriteQueryCommand):
    def get_name(self) -> str:
        return 'recent'

    def get_command_desc(self) -> str:
        return 'Analyze recent development activities in this codebase through current branch commit history'

    def get_query_content(self, user_input: UserInput) -> str:
        return RECENT_COMMAND


register_slash_command(StatusCommand())
register_slash_command(InitCommand())
register_slash_command(ClearCommand())
register_slash_command(CompactCommand())
register_slash_command(TodayCommand())
register_slash_command(RecentCommand())
register_slash_command(ContinueCommand())
# register_slash_command(CostCommand())
register_slash_command(MacSetupCommand())
