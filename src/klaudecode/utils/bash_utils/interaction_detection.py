class BashInteractionDetector:
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
    def detect_interactive_prompt(cls, text: str) -> bool:
        """Check if text contains interactive prompt patterns"""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in cls.INTERACTIVE_PATTERNS)

    @classmethod
    def detect_safe_continue_prompt(cls, text: str) -> bool:
        """Check if text contains safe continue prompt patterns that can be handled with ENTER"""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in cls.SAFE_CONTINUE_PATTERNS)
