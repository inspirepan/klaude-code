import asyncio
import signal
import subprocess
from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable
from rich.live import Live
from rich.markup import escape
from rich.text import Text

from ..message import UserMessage, render_message, render_suffix
from ..prompt.commands import BASH_INPUT_MODE_CONTENT
from ..tools.bash import BashTool
from ..tui import ColorStyle, console, get_prompt_toolkit_color
from ..user_input import CommandHandleOutput, InputModeCommand, UserInput

if TYPE_CHECKING:
    from ..agent import Agent


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.BASH_MODE)

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

            old_handler = signal.signal(signal.SIGINT, signal_handler)

            with Live(render_suffix(display_text), refresh_per_second=4, console=console.console) as live:
                # Read outputs concurrently
                while True:
                    if interrupted:
                        break

                    if process.poll() is not None:
                        # Process has finished
                        break

                    # Read available output
                    await asyncio.sleep(0.1)  # Small delay to prevent busy waiting

                    # Read stdout
                    if process.stdout.readable():
                        try:
                            line = process.stdout.readline()
                            if line:
                                output_lines.append(line.rstrip('\n'))
                                display_text.append(line)
                                live.update(render_suffix(display_text))
                        except Exception:
                            pass

                    # Read stderr
                    if process.stderr.readable():
                        try:
                            line = process.stderr.readline()
                            if line:
                                error_lines.append(line.rstrip('\n'))
                                display_text.append(line, style=ColorStyle.ERROR.value)
                                live.update(render_suffix(display_text))
                        except Exception:
                            pass

                # Read any remaining output
                try:
                    remaining_stdout, remaining_stderr = process.communicate(timeout=1)
                    if remaining_stdout:
                        output_lines.extend(remaining_stdout.rstrip('\n').split('\n'))
                        display_text.append(remaining_stdout)
                    if remaining_stderr:
                        error_lines.extend(remaining_stderr.rstrip('\n').split('\n'))
                        display_text.append(remaining_stderr, style=ColorStyle.ERROR.value)
                except subprocess.TimeoutExpired:
                    pass

                # Show exit code if non-zero or interrupted
                if interrupted:
                    display_text.append('\n[Process interrupted]', style=ColorStyle.WARNING.bold())
                    error_lines.append('[Process interrupted]')
                elif process.returncode != 0:
                    display_text.append(f'\n[Exit code: {process.returncode}]', style=ColorStyle.ERROR.bold())

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
        yield render_message(escape(user_msg.content), mark='!', style=self._get_color(), mark_style=self._get_color())

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')

        # Display stdout first, also display stderr if present
        if stdout:
            yield render_suffix(stdout)
        if stderr:
            yield render_suffix(Text(stderr, style=ColorStyle.ERROR.bold()))

    def get_content(self, user_msg: UserMessage) -> str:
        command = user_msg.content
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')
        return BASH_INPUT_MODE_CONTENT.format(command=command, stdout=stdout, stderr=stderr)
