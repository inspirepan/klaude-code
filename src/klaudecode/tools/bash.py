import os
import signal
import subprocess
import time
from typing import Annotated, Optional, Set

from pydantic import BaseModel, Field

from ..message import ToolCallMessage
from ..tool import Tool, ToolInstance


class BashTool(Tool):
    name = "Bash"
    desc = "Execute a bash command"

    # Dangerous commands that should be blocked
    DANGEROUS_COMMANDS: Set[str] = {
        'rm -rf /', 'rm -rf *', 'rm -rf ~', 'rm -rf .',
        'dd if=', 'mkfs', 'fdisk', 'parted',
        'shutdown', 'reboot', 'halt', 'poweroff',
        'sudo rm', 'sudo dd', 'sudo mkfs',
        'chmod 777', 'chown -R',
        'curl | sh', 'wget | sh', 'curl | bash', 'wget | bash',
        'eval', 'exec', 'source /dev/stdin'
    }

    # Commands that should use specialized tools
    SPECIALIZED_TOOLS = {
        'find': 'Use Glob or Grep tools instead of find command',
        'grep': 'Use Grep tool instead of grep command',
        'cat': 'Use Read tool instead of cat command',
        'head': 'Use Read tool instead of head command',
        'tail': 'Use Read tool instead of tail command',
        'ls': 'Use LS tool instead of ls command'
    }

    MAX_OUTPUT_SIZE = 30000  # Maximum output size to prevent memory overflow
    DEFAULT_TIMEOUT = 120000  # 2 minutes in milliseconds
    MAX_TIMEOUT = 600000  # 10 minutes in milliseconds

    class Input(BaseModel):
        command: Annotated[str, Field(description="The bash command to execute")]
        description: Annotated[Optional[str], Field(description="Description of what this command does")] = None
        timeout: Annotated[Optional[int], Field(description="Optional timeout in milliseconds (max 600000)")] = None

    @classmethod
    def _validate_command_safety(cls, command: str) -> tuple[bool, str]:
        """Validate command safety and return (is_safe, error_message)"""
        command_lower = command.lower().strip()

        # Check for dangerous commands
        for dangerous_cmd in cls.DANGEROUS_COMMANDS:
            if dangerous_cmd in command_lower:
                return False, f"Dangerous command detected: {dangerous_cmd}. This command is blocked for security reasons."

        # Check for specialized tools
        for cmd, suggestion in cls.SPECIALIZED_TOOLS.items():
            if command_lower.startswith(cmd + ' ') or command_lower == cmd:
                return False, f"Command '{cmd}' detected. {suggestion}"

        return True, ""

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
    def invoke(cls, tool_call: ToolCallMessage, instance: 'ToolInstance'):
        args: "BashTool.Input" = cls.parse_input_args(tool_call)

        # Validate command safety
        is_safe, error_msg = cls._validate_command_safety(args.command)
        if not is_safe:
            instance.tool_result().content = f"Error: {error_msg}"
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
                content += f"\n\n[Output truncated at {cls.MAX_OUTPUT_SIZE} characters to prevent memory overflow]"
            instance.tool_result().content = content

        try:
            # Start the process
            process = subprocess.Popen(
                args.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                preexec_fn=os.setsid  # Create new process group
            )

            # Initial content update
            output_lines.append(f"Executing: {args.command}")
            if args.description:
                output_lines.append(f"Description: {args.description}")
            output_lines.append("")
            update_content()

            start_time = time.time()

            # Read output in real-time
            while True:
                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    output_lines.append(f"\nCommand timed out after {timeout_seconds:.1f} seconds")
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
                                total_output_size += len(line) + 1  # +1 for newline
                            else:
                                break
                    break

                # Read a line with timeout
                try:
                    line = process.stdout.readline()
                    if line:
                        line = line.rstrip('\n\r')
                        if total_output_size < cls.MAX_OUTPUT_SIZE:
                            output_lines.append(line)
                            total_output_size += len(line) + 1  # +1 for newline
                            update_content()
                        else:
                            output_lines.append(f"[Output truncated at {cls.MAX_OUTPUT_SIZE} characters]")
                            update_content()
                            break
                    else:
                        # No more output, small delay to prevent busy waiting
                        time.sleep(0.01)
                except Exception as e:
                    output_lines.append(f"Error reading output: {str(e)}")
                    update_content()
                    break

            # Get exit code
            if process.poll() is not None:
                exit_code = process.returncode
                if exit_code != 0:
                    output_lines.append(f"\nCommand failed with exit code: {exit_code}")

            # Final content update
            update_content()

        except Exception as e:
            error_msg = f"Error executing command: {str(e)}"
            output_lines.append(error_msg)
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
