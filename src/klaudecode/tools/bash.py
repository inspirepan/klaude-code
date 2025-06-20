import os
import select
import signal
import subprocess
import sys
import time
from typing import Annotated, Optional, Set

from pydantic import BaseModel, Field

from ..message import ToolCall, register_tool_call_renderer, ToolMessage
from ..tool import Tool, ToolInstance
from rich.text import Text


class BashTool(Tool):
    name = 'Bash'
    desc = 'Execute a bash command'

    class Input(BaseModel):
        command: Annotated[str, Field(description='The bash command to execute')]
        description: Annotated[Optional[str], Field(description='Description of what this command does')] = None
        timeout: Annotated[
            Optional[int],
            Field(description='Optional timeout in milliseconds (max 600000)'),
        ] = None

        def __str__(self):
            return f'{self.description} → {self.command}'

    # Dangerous commands that should be blocked
    DANGEROUS_COMMANDS: Set[str] = {
        'rm -rf /',
        'rm -rf *',
        'rm -rf ~',
        'rm -rf .',
        'dd if=',
        'mkfs',
        'fdisk',
        'parted',
        'shutdown',
        'reboot',
        'halt',
        'poweroff',
        'sudo rm',
        'sudo dd',
        'sudo mkfs',
        'chmod 777',
        'chown -R',
        'curl | sh',
        'wget | sh',
        'curl | bash',
        'wget | bash',
        'eval',
        'exec',
        'source /dev/stdin',
    }

    # Commands that should use specialized tools
    SPECIALIZED_TOOLS = {
        'find': 'Use Glob or Grep tools instead of find command',
        'grep': 'Use Grep tool instead of grep command',
        'cat': 'Use Read tool instead of cat command',
        'head': 'Use Read tool instead of head command',
        'tail': 'Use Read tool instead of tail command',
        'ls': 'Use LS tool instead of ls command',
    }

    MAX_OUTPUT_SIZE = 30000  # Maximum output size to prevent memory overflow
    DEFAULT_TIMEOUT = 120000  # 2 minutes in milliseconds
    MAX_TIMEOUT = 600000  # 10 minutes in milliseconds

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'BashTool.Input' = cls.parse_input_args(tool_call)

        # Validate command safety
        is_safe, error_msg = cls._validate_command_safety(args.command)
        if not is_safe:
            instance.tool_result().set_error_msg(error_msg)
            return

        # Set timeout
        timeout_ms = args.timeout or cls.DEFAULT_TIMEOUT
        if timeout_ms > cls.MAX_TIMEOUT:
            timeout_ms = cls.MAX_TIMEOUT
        timeout_seconds = timeout_ms / 1000.0

        # Initialize output
        output_lines = []
        total_output_size = 0
        process = None

        def update_content():
            """Update the tool result content with current output"""
            content = '\n'.join(output_lines)
            if total_output_size >= cls.MAX_OUTPUT_SIZE:
                content += f'\n[Output truncated at {cls.MAX_OUTPUT_SIZE} characters]'
            instance.tool_result().set_content(content.strip())

        try:
            # Start the process
            process = subprocess.Popen(
                args.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                preexec_fn=os.setsid,  # Create new process group
            )

            # Initial content update
            update_content()

            start_time = time.time()

            # Read output in real-time with non-blocking approach
            while True:
                # Check if task was canceled
                if instance.tool_result().tool_call.status == 'canceled':
                    output_lines.append('Command interrupted by user')
                    update_content()
                    cls._kill_process_tree(process.pid)
                    break

                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    output_lines.append(f'Command timed out after {timeout_seconds:.1f} seconds')
                    update_content()
                    cls._kill_process_tree(process.pid)
                    break

                # Check if process is still running
                if process.poll() is not None:
                    # Process finished, read remaining output
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.splitlines():
                            if total_output_size < cls.MAX_OUTPUT_SIZE:
                                output_lines.append(line)
                                # +1 for newline
                                total_output_size += len(line) + 1
                            else:
                                break
                    break

                # Read process output
                total_output_size, should_break, error_msg = cls._read_process_output(process, output_lines, total_output_size, update_content)

                if error_msg:
                    instance.tool_result().set_error_msg(error_msg)
                    update_content()
                    break

                if should_break:
                    break

            # Get exit code
            if process.poll() is not None:
                exit_code = process.returncode
                if exit_code != 0:
                    output_lines.append(f'Exit code: {exit_code}')

            # Final content update
            update_content()

        except Exception as e:
            import traceback
            error_msg = f'Error executing command: {str(e)} {traceback.format_exc()}'
            instance.tool_result().set_error_msg(error_msg)
            update_content()

            # Clean up process if it exists
            if process and process.poll() is None:
                try:
                    cls._kill_process_tree(process.pid)
                except Exception:
                    pass

        finally:
            # Ensure process is cleaned up
            if process and process.poll() is None:
                try:
                    cls._kill_process_tree(process.pid)
                except Exception:
                    pass

    @classmethod
    def _validate_command_safety(cls, command: str) -> tuple[bool, str]:
        """Validate command safety and return (is_safe, error_message)"""
        command_lower = command.lower().strip()

        # Check for dangerous commands
        for dangerous_cmd in cls.DANGEROUS_COMMANDS:
            if dangerous_cmd in command_lower:
                return (
                    False,
                    f'Dangerous command detected: {dangerous_cmd}. This command is blocked for security reasons.',
                )

        # Check for specialized tools
        # TODO: Implement those tools
        # for cmd, suggestion in cls.SPECIALIZED_TOOLS.items():
        #     if command_lower.startswith(cmd + ' ') or command_lower == cmd:
        #         return False, f"Command '{cmd}' detected. {suggestion}"

        return True, ''

    @classmethod
    def _kill_process_tree(cls, pid: int):
        """Kill a process and all its children"""
        try:
            # Get all child processes
            children = []
            try:
                output = subprocess.check_output(['pgrep', '-P', str(pid)], stderr=subprocess.DEVNULL)
                children = [int(child_pid) for child_pid in output.decode().strip().split('\n') if child_pid]
            except subprocess.CalledProcessError:
                # No children found
                pass

            # Kill children first
            for child_pid in children:
                cls._kill_process_tree(child_pid)

            # Kill the main process
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                # Process already dead
                pass
        except Exception:
            # Ignore errors in cleanup
            pass

    @classmethod
    def _process_output_line(cls, line: str, output_lines: list, total_output_size: int, update_content_func) -> tuple[int, bool]:
        """Process a single output line and return (new_total_size, should_break)"""
        line = line.rstrip('\n\r')
        if total_output_size < cls.MAX_OUTPUT_SIZE:
            output_lines.append(line)
            total_output_size += len(line) + 1  # +1 for newline
            update_content_func()
            return total_output_size, False
        else:
            output_lines.append(f'[Output truncated at {cls.MAX_OUTPUT_SIZE} characters]')
            update_content_func()
            return total_output_size, True

    @classmethod
    def _read_process_output(cls, process, output_lines: list, total_output_size: int, update_content_func) -> tuple[int, bool, str]:
        """Read output from process. Returns (new_total_size, should_break, error_msg)"""
        if sys.platform != 'win32':
            # Unix-like systems: use select
            ready, _, _ = select.select([process.stdout], [], [], 0.1)
            if ready:
                try:
                    line = process.stdout.readline()
                    if line:
                        new_size, should_break = cls._process_output_line(line, output_lines, total_output_size, update_content_func)
                        return new_size, should_break, ''
                    else:
                        # Empty line, no more output
                        return total_output_size, False, ''
                except Exception as e:
                    return total_output_size, True, f'Error reading output: {str(e)}'
            else:
                # No data available, small delay
                time.sleep(0.01)
                return total_output_size, False, ''
        else:
            # Windows: use simple readline approach
            try:
                line = process.stdout.readline()
                if line:
                    new_size, should_break = cls._process_output_line(line, output_lines, total_output_size, update_content_func)
                    return new_size, should_break, ''
                else:
                    # No more output, small delay to prevent busy waiting
                    time.sleep(0.01)
                    return total_output_size, False, ''
            except Exception as e:
                return total_output_size, True, f'Error reading output: {str(e)}'


def render_bash_args(tool_call: ToolCall):
    description = tool_call.tool_args_dict.get('description', '')
    tool_call_msg = Text.assemble(
        (tool_call.tool_name, 'bold'),
        '(',
        f"{description} → " if description else "",
        tool_call.tool_args_dict.get('command', ''),
        ')',
    )
    yield tool_call_msg


register_tool_call_renderer('Bash', render_bash_args)
