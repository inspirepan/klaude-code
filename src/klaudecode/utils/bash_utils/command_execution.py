import os
import subprocess
import time
from typing import Callable

from .environment import BashEnvironment
from .output_processing import BashOutputProcessor
from .process_management import BashProcessManager


class BashCommandExecutor:
    # Execution constants
    DEFAULT_TIMEOUT = 300000  # 5 minutes in milliseconds
    MAX_TIMEOUT = 600000  # 10 minutes in milliseconds

    @classmethod
    def execute_bash_command(cls, command: str, timeout_seconds: float, check_canceled: Callable[[], bool], update_content: Callable[[str], None]) -> str:
        """
        Execute a bash command and return error message if any.

        Args:
            command: The command to execute
            timeout_seconds: Timeout in seconds
            check_canceled: Callback function to check if execution should be canceled
            update_content: Callback function to update content with current output

        Returns:
            Error message string if error occurred, empty string if successful
        """
        # Initialize output
        output_lines = []
        total_output_size = 0
        process = None

        def update_current_content():
            """Update the content with current output"""
            content = BashOutputProcessor.format_output_with_truncation(output_lines, total_output_size)
            update_content(content)

        try:
            # Set up non-interactive environment
            env = os.environ.copy()
            env.update(BashEnvironment.get_non_interactive_env())

            # Preprocess command to handle interactive tools
            processed_command = BashEnvironment.preprocess_command(command, timeout_seconds)

            # Start the process
            process = subprocess.Popen(
                processed_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,  # Disable stdin
                universal_newlines=True,
                bufsize=1,
                preexec_fn=os.setsid,  # Create new process group
                env=env,
            )

            # Initial content update
            update_current_content()

            start_time = time.time()

            # Read output in real-time with non-blocking approach
            while True:
                # Check if task was canceled (more frequently)
                if check_canceled():
                    output_lines.append('Command interrupted by user')
                    update_current_content()
                    BashProcessManager.kill_process_tree(process.pid)
                    break

                # Check timeout
                if time.time() - start_time > timeout_seconds:
                    output_lines.append(f'Command timed out after {timeout_seconds:.1f} seconds')
                    update_current_content()
                    BashProcessManager.kill_process_tree(process.pid)
                    break

                # Check if process is still running
                if process.poll() is not None:
                    # Process finished, read remaining output
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        # Strip ANSI codes from output
                        clean_output = BashEnvironment.strip_ansi_codes(remaining_output)
                        for line in clean_output.splitlines():
                            output_lines.append(line)
                            total_output_size += len(line) + 1  # +1 for newline
                    break

                # Read process output with interrupt checking
                total_output_size, should_break, error_msg = BashOutputProcessor.read_process_output(
                    process, output_lines, total_output_size, update_current_content, check_canceled
                )

                if error_msg:
                    update_current_content()
                    return error_msg

                if should_break:
                    break

            # Get exit code
            if process.poll() is not None:
                exit_code = process.returncode
                if exit_code != 0:
                    output_lines.append(f'Exit code: {exit_code}')

            # Final content update
            update_current_content()
            return ''  # No error

        except Exception as e:
            import traceback

            error_msg = f'Error executing command: {str(e)} {traceback.format_exc()}'
            update_current_content()
            return error_msg

        finally:
            # Ensure process is cleaned up
            if process and process.poll() is None:
                try:
                    BashProcessManager.kill_process_tree(process.pid)
                except Exception:
                    pass
