import select
import sys
import time

from .environment import BashEnvironment
from .interaction_detection import BashInteractionDetector


class BashOutputProcessor:
    # Output processing constants
    MAX_OUTPUT_SIZE = 30000
    TRUNCATE_PRESERVE_LINES = 200

    @classmethod
    def format_output_with_truncation(cls, output_lines: list, total_output_size: int) -> str:
        """Format output with middle truncation if needed to preserve start and end content"""
        if total_output_size < cls.MAX_OUTPUT_SIZE or len(output_lines) <= cls.TRUNCATE_PRESERVE_LINES * 2:
            return '\n'.join(output_lines)

        # Calculate how many lines to keep from start and end
        preserve_lines = cls.TRUNCATE_PRESERVE_LINES
        start_lines = output_lines[:preserve_lines]
        end_lines = output_lines[-preserve_lines:]

        # Calculate approximate character counts
        start_chars = sum(len(line) + 1 for line in start_lines)  # +1 for newline
        end_chars = sum(len(line) + 1 for line in end_lines)
        truncated_chars = total_output_size - start_chars - end_chars
        truncated_line_count = len(output_lines) - 2 * preserve_lines

        # Create truncation message
        truncation_msg = f'\n[... {truncated_line_count} lines ({truncated_chars} chars) truncated from middle ...]\n'

        # Combine start, truncation message, and end
        return '\n'.join(start_lines) + truncation_msg + '\n'.join(end_lines)

    @classmethod
    def process_output_line(cls, line: str, output_lines: list, total_output_size: int, update_content_func) -> tuple[int, bool]:
        """Process a single output line and return (new_total_size, should_break)"""
        line = line.rstrip('\n\r')

        # Strip ANSI codes from line
        clean_line = BashEnvironment.strip_ansi_codes(line)

        # Check for interactive prompts
        if BashInteractionDetector.detect_interactive_prompt(clean_line):
            output_lines.append(f'Interactive prompt detected: {clean_line}')
            output_lines.append('Command terminated due to interactive prompt')
            update_content_func()
            return total_output_size, True

        # Check for safe continue prompts that we can handle
        if BashInteractionDetector.detect_safe_continue_prompt(clean_line):
            output_lines.append(f'Safe continue prompt detected: {clean_line}')
            # We could handle this by sending ENTER, but for now just log it
            pass

        output_lines.append(clean_line)
        total_output_size += len(clean_line) + 1  # +1 for newline
        update_content_func()

        # Continue collecting output even after MAX_OUTPUT_SIZE to preserve end content
        return total_output_size, False

    @classmethod
    def read_process_output(cls, process, output_lines: list, total_output_size: int, update_content_func, check_canceled=None) -> tuple[int, bool, str]:
        """Read output from process. Returns (new_total_size, should_break, error_msg)"""
        if sys.platform != 'win32':
            # Unix-like systems: use select with shorter timeout for better responsiveness
            ready, _, _ = select.select([process.stdout], [], [], 0.05)  # Reduced from 0.1 to 0.05
            if ready:
                try:
                    line = process.stdout.readline()
                    if line:
                        new_size, should_break = cls.process_output_line(line, output_lines, total_output_size, update_content_func)
                        return new_size, should_break, ''
                    else:
                        # Empty line, no more output
                        return total_output_size, False, ''
                except Exception as e:
                    return total_output_size, True, f'Error reading output: {str(e)}'
            else:
                # No data available, check for cancellation before delay
                if check_canceled and check_canceled():
                    return total_output_size, True, ''
                time.sleep(0.005)  # Reduced delay for better responsiveness
                return total_output_size, False, ''
        else:
            # Windows: use simple readline approach with cancellation check
            try:
                line = process.stdout.readline()
                if line:
                    new_size, should_break = cls.process_output_line(line, output_lines, total_output_size, update_content_func)
                    return new_size, should_break, ''
                else:
                    # No more output, check cancellation before delay
                    if check_canceled and check_canceled():
                        return total_output_size, True, ''
                    time.sleep(0.005)  # Reduced delay for better responsiveness
                    return total_output_size, False, ''
            except Exception as e:
                return total_output_size, True, f'Error reading output: {str(e)}'
