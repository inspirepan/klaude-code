import re
from typing import Set


class BashSecurity:
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
        '| sh',
        '| bash',
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

    @classmethod
    def validate_command_safety(cls, command: str) -> tuple[bool, str]:
        """Validate command safety and return (is_safe, error_message)"""
        command_lower = command.lower().strip()

        # Check for dangerous commands with more precise matching
        for dangerous_cmd in cls.DANGEROUS_COMMANDS:
            # For single words, check word boundaries
            if dangerous_cmd in ['eval', 'exec']:
                # Use word boundary check for single dangerous commands
                pattern = r'\b' + re.escape(dangerous_cmd) + r'\b'
                if re.search(pattern, command_lower):
                    return (
                        False,
                        f'Dangerous command detected: {dangerous_cmd}. This command is blocked for security reasons.',
                    )
            else:
                # For multi-word patterns, use substring matching
                if dangerous_cmd in command_lower:
                    return (
                        False,
                        f'Dangerous command detected: {dangerous_cmd}. This command is blocked for security reasons.',
                    )

        # Check for specialized tools
        for cmd, suggestion in cls.SPECIALIZED_TOOLS.items():
            if command_lower.startswith(cmd + ' ') or command_lower == cmd:
                return True, f"<system-reminder>Command '{cmd}' detected. {suggestion}</system-reminder>"

        return True, ''
