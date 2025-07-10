import platform
import shutil
import subprocess
from typing import Generator

from rich.abc import RichRenderable
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..agent import AgentState
from ..message import UserMessage
from ..tui import ColorStyle
from ..user_input import Command, CommandHandleOutput, UserInput


class MacSetupCommand(Command):
    def get_name(self) -> str:
        return 'mac_setup'

    def get_command_desc(self) -> str:
        return 'Install fd, rg (ripgrep) using Homebrew on macOS for optimal performance'

    @classmethod
    def need_mac_setup(cls) -> bool:
        return platform.system() == 'Darwin' and shutil.which('brew') and (not shutil.which('fd') or not shutil.which('rg'))

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        # Check if running on macOS
        if platform.system() != 'Darwin':
            command_handle_output.user_msg.set_extra_data('setup_result', {'success': False, 'error': 'This command is only available on macOS'})
            return command_handle_output

        # Check if Homebrew is installed
        if not shutil.which('brew'):
            command_handle_output.user_msg.set_extra_data('setup_result', {'success': False, 'error': 'Homebrew is not installed. Please install Homebrew first: https://brew.sh'})
            return command_handle_output

        setup_results = []

        # Check and install fd
        fd_result = self._install_tool('fd', 'Fast file finder')
        setup_results.append(fd_result)

        # Check and install rg (ripgrep)
        rg_result = self._install_tool('rg', 'Fast text search tool', package_name='ripgrep')
        setup_results.append(rg_result)

        command_handle_output.user_msg.set_extra_data('setup_result', {'success': True, 'results': setup_results})
        return command_handle_output

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
            error_text = Text(f'✗ {setup_data.get("error", "Unknown error")}', style=ColorStyle.ERROR)
            yield Panel.fit(error_text, title='Mac Setup Failed', border_style=ColorStyle.ERROR)
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
                status_text = Text.assemble(
                    (f'✓ {tool}', ColorStyle.SUCCESS.bold),
                    (f' ({desc}) - Already installed', ColorStyle.HINT),
                    (f' - {version}', ColorStyle.HINT),
                )
            elif status == 'installed':
                status_text = Text.assemble(
                    (f'✓ {tool}', ColorStyle.SUCCESS.bold),
                    (f' ({desc}) - Successfully installed', ColorStyle.HINT),
                    (f' - {version}', ColorStyle.HINT),
                )
            else:  # failed
                status_text = Text.assemble(
                    (f'✗ {tool}', ColorStyle.ERROR.bold),
                    (f' ({desc}) - Failed', ColorStyle.HINT),
                    (f': {result.get("error", "")}', ColorStyle.ERROR),
                )

            result_items.append(status_text)

        if result_items:
            yield Panel.fit(
                Group(*result_items),
                border_style=ColorStyle.SUCCESS if all(r['status'] in ['already_installed', 'installed'] for r in results) else ColorStyle.WARNING,
            )
