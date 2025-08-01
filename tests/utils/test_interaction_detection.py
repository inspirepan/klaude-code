from klaudecode.utils.bash_utils.interaction_detection import BashInteractionDetector
from tests.base import BaseToolTest


class TestBashInteractionDetector(BaseToolTest):
    def test_detect_interactive_prompt_positive_cases(self):
        """Test detection of interactive prompts"""
        interactive_prompts = [
            "Enter password:",
            "Please enter passphrase for key",
            "Are you sure you want to continue?",
            "Do you want to proceed? (y/n)",
            "Continue? (y/n)",
            "Do you want to overwrite the file?",
            "Please confirm the action",
            "Type 'yes' to continue",
            "Press h for help",
            "Press q to quit",
            "PASSWORD:",  # Case insensitive
            "CONFIRM (y/n)",
            "enter passphrase for SSH key",
            "are you sure you want to delete",
        ]

        for prompt in interactive_prompts:
            result = BashInteractionDetector.detect_interactive_prompt(prompt)
            assert result is True, f"'{prompt}' should be detected as interactive"

    def test_detect_interactive_prompt_negative_cases(self):
        """Test that non-interactive text is not detected as prompts"""
        non_interactive_text = [
            "Processing files...",
            "Build completed successfully",
            "Running tests",
            "File downloaded",
            "Command executed",
            "Installation in progress",
            "Analyzing code",
            "Compilation finished",
            "Test results: PASSED",
            "Server starting on port 8080",
            "Log: User authenticated",
            "Debug: Function called",
            "Info: Configuration loaded",
        ]

        for text in non_interactive_text:
            result = BashInteractionDetector.detect_interactive_prompt(text)
            assert result is False, f"'{text}' should NOT be detected as interactive"

    def test_detect_interactive_prompt_case_insensitive(self):
        """Test that detection is case insensitive"""
        case_variations = [
            ("password:", True),
            ("Password:", True),
            ("PASSWORD:", True),
            ("PaSSwoRd:", True),
            ("confirm (y/n)", True),
            ("CONFIRM (Y/N)", True),
            ("Are You Sure", True),
            ("ARE YOU SURE", True),
        ]

        for text, expected in case_variations:
            result = BashInteractionDetector.detect_interactive_prompt(text)
            assert result == expected, f"'{text}' case sensitivity test failed"

    def test_detect_interactive_prompt_partial_matches(self):
        """Test that partial matches within larger text are detected"""
        texts_with_prompts = [
            "Error occurred. Enter password: to retry",
            "Setup complete. Are you sure you want to continue? Press enter.",
            "Configuration saved. Do you want to restart the service? (y/n)",
            "Files copied. Press h for help or q to quit.",
            "Installation finished. Type 'yes' to confirm settings.",
        ]

        for text in texts_with_prompts:
            result = BashInteractionDetector.detect_interactive_prompt(text)
            assert result is True, f"'{text}' should detect embedded interactive prompt"

    def test_detect_safe_continue_prompt_positive_cases(self):
        """Test detection of safe continue prompts"""
        safe_prompts = [
            "Press enter to continue",
            "Press ENTER to proceed",
            "Hit enter to continue with installation",
            "--More--",
            "(press SPACE to continue)",
            "Hit ENTER for next page",
            "WARNING: terminal is not fully functional",
            "terminal is not fully functional - press ENTER",
            "Press ENTER or type command to continue",
            "Hit ENTER for more information",
            "(END)",
            "Press any key to continue",
            "press return to continue",
            "PRESS ENTER TO CONTINUE",  # Case insensitive
            "Press Return Key",
        ]

        for prompt in safe_prompts:
            result = BashInteractionDetector.detect_safe_continue_prompt(prompt)
            assert result is True, (
                f"'{prompt}' should be detected as safe continue prompt"
            )

    def test_detect_safe_continue_prompt_negative_cases(self):
        """Test that non-safe prompts are not detected as safe continue"""
        non_safe_prompts = [
            "Enter password:",
            "Are you sure? (y/n)",
            "Type yes to confirm",
            "Press h for help",
            "Processing...",
            "Command completed",
            "Enter username:",
            "Select option [1-5]:",
            "Confirm deletion (y/n)",
        ]

        for prompt in non_safe_prompts:
            result = BashInteractionDetector.detect_safe_continue_prompt(prompt)
            assert result is False, (
                f"'{prompt}' should NOT be detected as safe continue prompt"
            )

    def test_detect_safe_continue_prompt_case_insensitive(self):
        """Test that safe continue detection is case insensitive"""
        case_variations = [
            "press enter to continue",
            "Press Enter To Continue",
            "PRESS ENTER TO CONTINUE",
            "PrEsS eNtEr To CoNtInUe",
            "--more--",
            "--MORE--",
            "(end)",
            "(END)",
            "press any key",
            "PRESS ANY KEY",
        ]

        for text in case_variations:
            result = BashInteractionDetector.detect_safe_continue_prompt(text)
            assert result is True, (
                f"'{text}' case sensitivity test failed for safe continue"
            )

    def test_interactive_patterns_constant(self):
        """Test that INTERACTIVE_PATTERNS constant contains expected patterns"""
        expected_patterns = [
            "password",
            "enter passphrase",
            "are you sure",
            "(y/n)",
            "continue?",
            "do you want to",
            "confirm",
            "type 'yes'",
            "press h for help",
            "press q to quit",
        ]

        for pattern in expected_patterns:
            assert pattern in BashInteractionDetector.INTERACTIVE_PATTERNS, (
                f"Pattern '{pattern}' missing from INTERACTIVE_PATTERNS"
            )

    def test_safe_continue_patterns_constant(self):
        """Test that SAFE_CONTINUE_PATTERNS constant contains expected patterns"""
        expected_patterns = [
            "press enter",
            "enter to continue",
            "--more--",
            "(press space to continue)",
            "hit enter to continue",
            "warning: terminal is not fully functional",
            "terminal is not fully functional",
            "press enter or type command to continue",
            "hit enter for",
            "(end)",
            "press any key",
            "press return to continue",
        ]

        for pattern in expected_patterns:
            assert pattern in BashInteractionDetector.SAFE_CONTINUE_PATTERNS, (
                f"Pattern '{pattern}' missing from SAFE_CONTINUE_PATTERNS"
            )

    def test_empty_and_whitespace_input(self):
        """Test handling of empty and whitespace-only input"""
        empty_inputs = ["", "   ", "\t", "\n", "\r\n", "  \t  \n  "]

        for text in empty_inputs:
            interactive_result = BashInteractionDetector.detect_interactive_prompt(text)
            safe_result = BashInteractionDetector.detect_safe_continue_prompt(text)

            assert interactive_result is False, (
                f"Empty/whitespace '{repr(text)}' should not be interactive"
            )
            assert safe_result is False, (
                f"Empty/whitespace '{repr(text)}' should not be safe continue"
            )

    def test_pattern_overlap_handling(self):
        """Test handling of text that could match both interactive and safe continue patterns"""
        # These should be detected as interactive (more specific/dangerous)
        ambiguous_texts = [
            "Press enter to continue or type password:",
            "Continue? Press enter or (y/n)",
            "Enter password or press enter to continue",
        ]

        for text in ambiguous_texts:
            interactive_result = BashInteractionDetector.detect_interactive_prompt(text)
            BashInteractionDetector.detect_safe_continue_prompt(text)

            # Interactive detection should take precedence for safety
            assert interactive_result is True, (
                f"'{text}' should be detected as interactive"
            )

    def test_multiline_text_detection(self):
        """Test detection in multiline text"""
        multiline_interactive = """
        Installation is starting...
        Enter password: 
        Processing...
        """

        multiline_safe = """
        Download complete.
        Press enter to continue
        with installation.
        """

        assert (
            BashInteractionDetector.detect_interactive_prompt(multiline_interactive)
            is True
        )
        assert (
            BashInteractionDetector.detect_safe_continue_prompt(multiline_safe) is True
        )

    def test_special_characters_in_prompts(self):
        """Test detection with special characters and formatting"""
        special_prompts = [
            "[sudo] password for user:",
            ">>> Enter passphrase <<<",
            "*** Are you sure? (y/n) ***",
            "=== Press enter to continue ===",
            "--- Type 'yes' to confirm ---",
            "~~~ Hit ENTER for more ~~~",
        ]

        for prompt in special_prompts:
            if any(
                pattern in prompt.lower()
                for pattern in [
                    "password",
                    "passphrase",
                    "are you sure",
                    "(y/n)",
                    "type 'yes'",
                ]
            ):
                result = BashInteractionDetector.detect_interactive_prompt(prompt)
                assert result is True, f"'{prompt}' should be detected as interactive"

            if any(
                pattern in prompt.lower() for pattern in ["press enter", "hit enter"]
            ):
                result = BashInteractionDetector.detect_safe_continue_prompt(prompt)
                assert result is True, f"'{prompt}' should be detected as safe continue"
