"""Tests for BashUtils class"""

import pytest
from klaudecode.utils.bash_utils import BashUtils


class TestBashUtils:
    def test_preprocess_command_with_quotes(self):
        """Test that commands with quotes are properly escaped"""
        test_cases = [
            # Simple command with single quotes
            {
                'command': 'echo \'Hello World\'',
                'expected_contains': ['echo \'Hello World\''],
            },
            # Python command with nested quotes
            {
                'command': 'python -c "print(\'Success\')"',
                'expected_contains': ['python -c "print(\'Success\')"'],
            },
            # Complex command with quotes that needs bash wrapper
            {
                'command': 'echo \'test\' | cat',
                'expected_contains': ['bash -c', 'echo', 'test', 'cat'],
            },
            # Command with unicode in quotes
            {
                'command': 'python -c "print(\'成功\')"',
                'expected_contains': ['python -c "print(\'成功\')"'],
            },
        ]

        for case in test_cases:
            result = BashUtils.preprocess_command(case['command'])
            for expected in case['expected_contains']:
                assert expected in result, f"Expected '{expected}' in result '{result}'"

    def test_needs_bash_wrapper(self):
        """Test detection of commands that need bash wrapper"""
        # Commands that should need wrapper
        wrapper_needed = [
            'echo test | cat',
            'export FOO=bar; echo $FOO',
            'command1 && command2',
            'command1 || command2',
            'result=$(echo test)',
            'for i in 1 2 3; do echo $i; done',
        ]

        for cmd in wrapper_needed:
            assert BashUtils._needs_bash_wrapper(cmd), f"Command '{cmd}' should need bash wrapper"

        # Commands that should NOT need wrapper
        no_wrapper_needed = [
            'echo test',
            'python script.py',
            'ls -la',
            'git status',
            'npm install',
        ]

        for cmd in no_wrapper_needed:
            assert not BashUtils._needs_bash_wrapper(cmd), f"Command '{cmd}' should NOT need bash wrapper"

    def test_strip_ansi_codes(self):
        """Test ANSI code stripping"""
        test_cases = [
            ('\x1b[31mRed Text\x1b[0m', 'Red Text'),
            ('\x1b[1;32mBold Green\x1b[0m', 'Bold Green'),
            ('\x1b[2J\x1b[HClear Screen', 'Clear Screen'),
            ('Normal text', 'Normal text'),
        ]

        for input_text, expected in test_cases:
            result = BashUtils.strip_ansi_codes(input_text)
            assert result == expected, f"Expected '{expected}', got '{result}'"

    def test_detect_interactive_prompt(self):
        """Test detection of interactive prompts"""
        interactive_prompts = [
            'Enter password:',
            'Are you sure you want to continue? (y/n)',
            'Please confirm:',
            'Do you want to proceed?',
        ]

        for prompt in interactive_prompts:
            assert BashUtils.detect_interactive_prompt(prompt), f"'{prompt}' should be detected as interactive"

        non_interactive = [
            'Processing file...',
            'Command completed',
            'Building project',
        ]

        for text in non_interactive:
            assert not BashUtils.detect_interactive_prompt(text), f"'{text}' should NOT be detected as interactive"