import asyncio
import signal
import subprocess
from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable
from rich.live import Live
from rich.text import Text

from .message import UserMessage, render_message, render_suffix
from .prompt.commands import BASH_INPUT_MODE_CONTENT
from .tools.bash import BashTool
from .tui import console
from .user_input import CommandHandleOutput, InputModeCommand, UserInput, register_input_mode

if TYPE_CHECKING:
    from .agent import Agent


# Input Modes
# ---------------------


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return '#6aa4a5'

    def get_placeholder(self) -> str:
        return 'type to start planning...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    # TODO: Implement handle


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return '#ea3386'

    def get_placeholder(self) -> str:
        return 'type a bash command...'

    def binding_key(self) -> str:
        return '!'

    async def handle(self, agent: 'Agent', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent, user_input)
        command = user_input.cleaned_input

        # Safety check
        is_safe, error_msg = BashTool.validate_command_safety(command)
        if not is_safe:
            error_result = f'Error: {error_msg}'
            command_handle_output.user_msg.set_extra_data('stdout', '')
            command_handle_output.user_msg.set_extra_data('stderr', error_result)
            return command_handle_output

        # Execute command and display output in streaming mode
        stdout, stderr = await self._execute_command_with_live_output(command)
        command_handle_output.user_msg.set_extra_data('stdout', stdout)
        command_handle_output.user_msg.set_extra_data('stderr', stderr)
        command_handle_output.need_render_suffix = False
        command_handle_output.need_agent_run = False
        return command_handle_output

    async def _execute_command_with_live_output(self, command: str) -> tuple[str, str]:
        """Execute command with live output display using rich.live, returns stdout and stderr"""
        output_lines = []
        error_lines = []
        process = None

        # Create display text
        display_text = Text()

        try:
            # Start process, capture stdout and stderr separately
            process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, bufsize=0)

            interrupted = False

            def signal_handler(signum, frame):
                nonlocal interrupted
                interrupted = True
                if process and process.poll() is None:
                    try:
                        BashTool._kill_process_tree(process.pid)
                    except Exception:
                        pass

            # Set signal handler
            old_handler = signal.signal(signal.SIGINT, signal_handler)

            with Live(render_suffix(display_text), console=console.console, refresh_per_second=10) as live:
                while process.poll() is None and not interrupted:
                    try:
                        # Read stdout
                        stdout_output = process.stdout.readline()
                        if stdout_output:
                            output_lines.append(stdout_output.rstrip())
                            # Update display (only show stdout)
                            display_text = Text()
                            for line in output_lines[-50:]:  # Only show last 50 lines
                                display_text.append(line + '\n')
                            live.update(render_suffix(display_text))
                        else:
                            await asyncio.sleep(0.01)
                    except Exception:
                        break

                # Ensure remaining output is captured
                if process.poll() is not None and not interrupted:
                    remaining_stdout = process.stdout.read()
                    remaining_stderr = process.stderr.read()

                    if remaining_stdout:
                        for line in remaining_stdout.strip().split('\n'):
                            if line:
                                output_lines.append(line)

                    if remaining_stderr:
                        for line in remaining_stderr.strip().split('\n'):
                            if line:
                                error_lines.append(line)

                # Final display update
                display_text = Text()
                for line in output_lines:
                    display_text.append(line + '\n')

                if interrupted:
                    display_text.append('\n[Command interrupted by user]', style='bold red')
                    error_lines.append('Command interrupted by user')
                elif process.poll() is not None and process.returncode != 0:
                    display_text.append(f'\n[Exit code: {process.returncode}]', style='bold red')

                live.update(render_suffix(display_text))

            # Restore signal handler
            signal.signal(signal.SIGINT, old_handler)

        except Exception as e:
            error_lines.append(f'Error executing command: {str(e)}')

        finally:
            # Clean up process
            if process and process.poll() is None:
                try:
                    BashTool._kill_process_tree(process.pid)
                except Exception:
                    pass

        # Return stdout and stderr
        return '\n'.join(output_lines), '\n'.join(error_lines)

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(user_msg.content, mark='!', style=self._get_color(), mark_style=self._get_color())

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')

        # Display stdout first, also display stderr if present
        if stdout:
            yield render_suffix(stdout)
        if stderr:
            yield render_suffix(Text(stderr, style='bold red'))

    def get_content(self, user_msg: UserMessage) -> str:
        command = user_msg.content
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')
        return BASH_INPUT_MODE_CONTENT.format(command=command, stdout=stdout, stderr=stderr)


class MemoryMode(InputModeCommand):
    def get_name(self) -> str:
        return 'memory'

    def _get_prompt(self) -> str:
        return '#'

    def _get_color(self) -> str:
        return '#b3b9f4'

    def get_placeholder(self) -> str:
        return 'type to memorize...'

    def binding_key(self) -> str:
        return '#'

    # TODO: Implement handle


register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
