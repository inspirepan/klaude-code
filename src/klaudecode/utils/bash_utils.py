import re


class BashUtils:
    INTERACTIVE_PATTERNS = [
        'password:',
        'enter passphrase',
        'are you sure',
        '(y/n)',
        'continue?',
        'do you want to',
        'confirm',
        "type 'yes'",
        'press h for help',
        'press q to quit',
    ]

    # Patterns that can be safely handled by sending ENTER
    SAFE_CONTINUE_PATTERNS = [
        'press enter',
        'enter to continue',
        '--More--',
        '(press SPACE to continue)',
        'hit enter to continue',
        'WARNING: terminal is not fully functional',
        'terminal is not fully functional',
        'Press ENTER or type command to continue',
        'Hit ENTER for',
        '(END)',
        'Press any key to continue',
        'press return to continue',
    ]

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
    def preprocess_command(cls, command: str) -> str:
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

        return f'timeout 30s {command}'

    @classmethod
    def strip_ansi_codes(cls, data: str) -> str:
        """Strip ANSI escape codes from output"""
        return re.sub(r'\x1b\[[0-9;]*[HJKmlsu]|\x1b\[[\?][0-9;]*[hlc]|\x1b\][0-9];[^\x07]*\x07|\x1b\(|\x1b\)|\x1b\[s|\x1b\[u', '', data)

    @classmethod
    def detect_interactive_prompt(cls, text: str) -> bool:
        """Check if text contains interactive prompt patterns"""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in cls.INTERACTIVE_PATTERNS)

    @classmethod
    def detect_safe_continue_prompt(cls, text: str) -> bool:
        """Check if text contains safe continue prompt patterns that can be handled with ENTER"""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in cls.SAFE_CONTINUE_PATTERNS)
