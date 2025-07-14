import re
import shlex
import shutil


class BashEnvironment:
    @classmethod
    def get_non_interactive_env(cls) -> dict:
        """Get environment variables for non-interactive execution"""
        return {
            'DEBIAN_FRONTEND': 'noninteractive',
            'PYTHONUNBUFFERED': '1',
            'BATCH': '1',
            'NONINTERACTIVE': '1',
            'CI': 'true',
            'TERM': 'dumb',
            'SSH_ASKPASS': '',
            'SSH_ASKPASS_REQUIRE': 'never',
            'GIT_ASKPASS': 'echo',
            'SUDO_ASKPASS': '/bin/false',
            'GPG_TTY': '',
            'GIT_PAGER': 'cat',
            'PAGER': 'cat',
            'LESS': '',
            'MORE': '',
            'MANPAGER': 'cat',
            'SYSTEMD_PAGER': '',
            'BAT_PAGER': '',
            'DELTA_PAGER': 'cat',
            'LESSOPEN': '',
            'LESSCLOSE': '',
            'NO_COLOR': '1',
            'FORCE_COLOR': '0',
            'CLICOLOR': '0',
            'CLICOLOR_FORCE': '0',
            'CURL_CA_BUNDLE': '',
            'HOMEBREW_NO_ANALYTICS': '1',
            'HOMEBREW_NO_AUTO_UPDATE': '1',
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONIOENCODING': 'utf-8',
            'EDITOR': 'cat',
            'VISUAL': 'cat',
        }

    @classmethod
    def preprocess_command(cls, command: str, timeout_seconds: float = 30.0) -> str:
        """Preprocess command to handle interactive tools"""

        # Replace common interactive tools with non-interactive alternatives
        replacements = {
            r'\|\s*more\b': '| cat',
            r'\|\s*less\b': '| cat',
            r'\b(vi|vim|nano|emacs)\s+': r'cat ',
            r'\b(less)\b(?!\s*-)': r'cat',
            r'\b(more)\b(?!\s*-)': r'cat',
        }

        for pattern, replacement in replacements.items():
            command = re.sub(pattern, replacement, command)

        # Check if command already has timeout
        has_timeout = command.strip().startswith('timeout ')

        # Check if command needs bash -c wrapping by detecting complex shell syntax
        needs_bash_wrapper = cls._needs_bash_wrapper(command)

        # Only add timeout if not already present
        if not has_timeout and cls._has_timeout_command():
            timeout_str = f'{timeout_seconds:.0f}s'
            if needs_bash_wrapper:
                # Use shlex.quote to properly escape the command for bash -c
                escaped_command = shlex.quote(command)
                return f'timeout {timeout_str} bash -c {escaped_command}'
            else:
                return f'timeout {timeout_str} {command}'
        else:
            # If timeout is not available or already present, return command as-is
            if needs_bash_wrapper and not has_timeout:
                escaped_command = shlex.quote(command)
                return f'bash -c {escaped_command}'
            else:
                return command

    @classmethod
    def _has_timeout_command(cls) -> bool:
        """Check if the timeout command is available on the system"""
        return shutil.which('timeout') is not None

    @classmethod
    def strip_ansi_codes(cls, data: str) -> str:
        """Strip ANSI escape codes from output"""
        return re.sub(r'\x1b\[[0-9;]*[HJKmlsu]|\x1b\[[\?][0-9;]*[hlc]|\x1b\][0-9];[^\x07]*\x07|\x1b\(|\x1b\)|\x1b\[s|\x1b\[u', '', data)

    @classmethod
    def _needs_bash_wrapper(cls, command: str) -> bool:
        """Check if command needs bash -c wrapping based on shell syntax complexity"""
        # Remove quoted strings to avoid false positives
        cleaned_command = re.sub(r'["\'].*?["\']', '', command)

        # Check for shell metacharacters that indicate complex syntax
        complex_chars = [';', '|', '&', '(', ')', '{', '}', '[', ']']
        has_complex_chars = any(char in cleaned_command for char in complex_chars)

        # Check for shell operators
        shell_operators = ['&&', '||', '>>', '<<', '2>', '&>', '|&']
        has_operators = any(op in cleaned_command for op in shell_operators)

        # Check for shell keywords
        shell_keywords = ['for', 'while', 'if', 'case', 'function', 'do', 'done', 'then', 'else', 'fi', 'esac']
        has_keywords = any(re.search(r'\b' + keyword + r'\b', cleaned_command, re.IGNORECASE) for keyword in shell_keywords)

        # Check for variable assignments
        has_assignment = re.search(r'\w+=', cleaned_command)

        # Check for command substitution
        has_substitution = '`' in cleaned_command or '$(' in cleaned_command

        return has_complex_chars or has_operators or has_keywords or has_assignment or has_substitution
