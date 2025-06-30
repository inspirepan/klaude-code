import asyncio
import os
import pty
import select
import signal
import subprocess
from typing import TYPE_CHECKING, Generator

from rich.abc import RichRenderable
from rich.live import Live
from rich.text import Text

from ..message import UserMessage
from ..prompt.commands import BASH_INPUT_MODE_CONTENT
from ..tools.bash import BashTool
from ..tui import ColorStyle, console, get_prompt_toolkit_color, render_message, render_suffix
from ..user_input import CommandHandleOutput, InputModeCommand, UserInput
from ..utils.bash_utils import BashUtils

if TYPE_CHECKING:
    from ..agent import Agent


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return get_prompt_toolkit_color(ColorStyle.BASH_MODE)

    def _get_placeholder(self) -> str:
        return 'type a bash command...'

    def binding_key(self) -> str:
        return '!'

    def binding_keys(self) -> list[str]:
        return ['!', '！']

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

        processed_command = BashUtils.preprocess_command(command)

        # Execute command and display output in streaming mode
        stdout, stderr = await self._execute_command_with_live_output(processed_command)
        command_handle_output.user_msg.set_extra_data('stdout', stdout)
        command_handle_output.user_msg.set_extra_data('stderr', stderr)
        command_handle_output.need_render_suffix = False
        command_handle_output.need_agent_run = False
        return command_handle_output

    async def _execute_command_with_live_output(self, command: str) -> tuple[str, str]:
        """Execute command with live output display using pty for real streaming"""
        output_lines = []
        error_lines = []
        master_fd = None
        process = None

        display_text = Text()

        try:
            processed_command = BashUtils.preprocess_command(command)

            env = os.environ.copy()
            env.update(BashUtils.get_non_interactive_env())

            master_fd, slave_fd = pty.openpty()

            process = subprocess.Popen(
                processed_command,
                shell=True,
                stdout=slave_fd,
                stderr=subprocess.STDOUT,
                stdin=slave_fd,
                universal_newlines=True,
                preexec_fn=os.setsid,
                env=env,
            )

            os.close(slave_fd)

            interrupted = False

            def signal_handler(signum, frame):
                nonlocal interrupted
                interrupted = True
                if process and process.poll() is None:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    except Exception:
                        pass

            old_handler = signal.signal(signal.SIGINT, signal_handler)

            with Live(render_suffix(display_text), refresh_per_second=10, console=console.console) as live:
                partial_line = ''

                while True:
                    if interrupted:
                        break

                    if process.poll() is not None:
                        break

                    try:
                        ready, _, _ = select.select([master_fd], [], [], 0.01)
                        if ready:
                            data = os.read(master_fd, 4096).decode('utf-8', errors='replace')
                            if data:
                                data = BashUtils.strip_ansi_codes(data)
                                lines = (partial_line + data).split('\n')
                                partial_line = lines[-1]

                                for line in lines[:-1]:
                                    if BashUtils.detect_safe_continue_prompt(line):
                                        # Send ENTER key for safe continue prompts
                                        display_text.append(f'Auto-continuing from prompt: {line}\n')
                                        try:
                                            os.write(master_fd, b'\n')
                                        except OSError:
                                            pass
                                        output_lines.append(line)
                                        display_text.append(line + '\n')
                                        continue
                                    elif BashUtils.detect_interactive_prompt(line):
                                        display_text.append(f'Interactive prompt detected: {line}\n')
                                        display_text.append('Command terminated due to interactive prompt\n')
                                        live.update(render_suffix(display_text))
                                        try:
                                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                                        except Exception:
                                            pass
                                        return '\n'.join(output_lines), '[Process interrupted]'

                                    output_lines.append(line)
                                    display_text.append(line + '\n')

                                if partial_line:
                                    display_text.append(partial_line)

                                live.update(render_suffix(display_text))
                    except (OSError, UnicodeDecodeError):
                        break

                    await asyncio.sleep(0.01)

                if partial_line:
                    output_lines.append(partial_line)
                    display_text.append(partial_line)

                if interrupted:
                    display_text.append('\n[Process interrupted]', style=ColorStyle.WARNING)
                    error_lines.append('[Process interrupted]')
                elif process.returncode != 0:
                    display_text.append(f'\n[Exit code: {process.returncode}]', style=ColorStyle.ERROR)

                live.update(render_suffix(display_text))

            signal.signal(signal.SIGINT, old_handler)

        except Exception as e:
            error_lines.append(f'Error executing command: {str(e)}')

        finally:
            if master_fd is not None:
                try:
                    os.close(master_fd)
                except OSError:
                    pass

            if process and process.poll() is None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except Exception:
                    pass

        return '\n'.join(output_lines), '\n'.join(error_lines)

    def render_user_msg(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        yield render_message(Text(user_msg.content), mark='!', style=self._get_color(), mark_style=self._get_color())

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')

        # Display stdout first, also display stderr if present
        if stdout:
            yield render_suffix(stdout)
        if stderr:
            yield render_suffix(Text(stderr, style=ColorStyle.ERROR))

    def get_content(self, user_msg: UserMessage) -> str:
        command = user_msg.content
        stdout = user_msg.get_extra_data('stdout', '')
        stderr = user_msg.get_extra_data('stderr', '')
        return BASH_INPUT_MODE_CONTENT.format(command=command, stdout=stdout, stderr=stderr)
