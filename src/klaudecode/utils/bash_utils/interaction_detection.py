class BashInteractionDetector:
    INTERACTIVE_PATTERNS = [
        'password',
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
        '--more--',
        '(press space to continue)',
        'hit enter to continue',
        'warning: terminal is not fully functional',
        'terminal is not fully functional',
        'press enter or type command to continue',
        'hit enter for',
        '(end)',
        'press any key',
        'press return to continue',
        'press return key',
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
