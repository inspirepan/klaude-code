"""Tests for bash_utils modules - Environment and Interaction Detection"""

import unittest.mock

from klaudecode.utils.bash_utils.environment import BashEnvironment
from klaudecode.utils.bash_utils.interaction_detection import BashInteractionDetector
from tests.base import BaseToolTest


class TestBashEnvironment(BaseToolTest):
    def test_preprocess_command_with_quotes(self):
        """Test that commands with quotes are properly escaped"""
        # Mock timeout availability to make tests predictable
        with unittest.mock.patch.object(BashEnvironment, '_has_timeout_command', return_value=True):
            test_cases = [
                # Simple command with single quotes
                {
                    'command': "echo 'Hello World'",
                    'expected_contains': ["echo 'Hello World'", 'timeout'],
                },
                # Python command with nested quotes
                {
                    'command': 'python -c "print(\'Success\')"',
                    'expected_contains': ['python -c "print(\'Success\')"', 'timeout'],
                },
                # Complex command with quotes that needs bash wrapper
                {
                    'command': "echo 'test' | cat",
                    'expected_contains': ['bash -c', 'echo', 'test', 'cat', 'timeout'],
                },
                # Command with unicode in quotes
                {
                    'command': 'python -c "print(\'成功\')"',
                    'expected_contains': ['python -c "print(\'成功\')"', 'timeout'],
                },
            ]

            for case in test_cases:
                result = BashEnvironment.preprocess_command(case['command'])
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
            assert BashEnvironment._needs_bash_wrapper(cmd), f"Command '{cmd}' should need bash wrapper"

        # Commands that should NOT need wrapper
        no_wrapper_needed = [
            'echo test',
            'python script.py',
            'ls -la',
            'git status',
            'npm install',
        ]

        for cmd in no_wrapper_needed:
            assert not BashEnvironment._needs_bash_wrapper(cmd), f"Command '{cmd}' should NOT need bash wrapper"

    def test_strip_ansi_codes(self):
        """Test ANSI code stripping"""
        test_cases = [
            ('\x1b[31mRed Text\x1b[0m', 'Red Text'),
            ('\x1b[1;32mBold Green\x1b[0m', 'Bold Green'),
            ('\x1b[2J\x1b[HClear Screen', 'Clear Screen'),
            ('Normal text', 'Normal text'),
        ]

        for input_text, expected in test_cases:
            result = BashEnvironment.strip_ansi_codes(input_text)
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
            assert BashInteractionDetector.detect_interactive_prompt(prompt), f"'{prompt}' should be detected as interactive"

        non_interactive = [
            'Processing file...',
            'Command completed',
            'Building project',
        ]

        for text in non_interactive:
            assert not BashInteractionDetector.detect_interactive_prompt(text), f"'{text}' should NOT be detected as interactive"

    def test_has_timeout_command(self):
        """Test detection of timeout command availability"""
        # Test when timeout is available
        with unittest.mock.patch('shutil.which', return_value='/usr/bin/timeout'):
            assert BashEnvironment._has_timeout_command() is True

        # Test when timeout is not available
        with unittest.mock.patch('shutil.which', return_value=None):
            assert BashEnvironment._has_timeout_command() is False

    def test_preprocess_command_with_timeout_available(self):
        """Test command preprocessing when timeout is available"""
        with unittest.mock.patch.object(BashEnvironment, '_has_timeout_command', return_value=True):
            # Simple command
            result = BashEnvironment.preprocess_command('echo test', 5.0)
            assert result == 'timeout 5s echo test'

            # Complex command needing bash wrapper
            result = BashEnvironment.preprocess_command('echo test | cat', 10.0)
            assert result.startswith('timeout 10s bash -c')
            assert 'echo test | cat' in result

    def test_preprocess_command_without_timeout(self):
        """Test command preprocessing when timeout is not available"""
        with unittest.mock.patch('klaudecode.utils.bash_utils.environment.BashEnvironment._has_timeout_command', return_value=False):
            # Simple command
            result = BashEnvironment.preprocess_command('echo test', 5.0)
            assert result == 'echo test'
            assert 'timeout' not in result

            # Complex command needing bash wrapper
            result = BashEnvironment.preprocess_command('echo test | cat', 10.0)
            assert result.startswith('bash -c')
            assert 'echo test | cat' in result
            assert 'timeout' not in result

    def test_preprocess_command_with_existing_timeout(self):
        """Test that commands already containing timeout are not double-wrapped"""
        with unittest.mock.patch.object(BashEnvironment, '_has_timeout_command', return_value=True):
            # Command already has timeout
            result = BashEnvironment.preprocess_command('timeout 30s uv run pytest', 5.0)
            assert result == 'timeout 30s uv run pytest'
            # Should not contain double timeout
            assert result.count('timeout') == 1

            # Command with different timeout format
            result = BashEnvironment.preprocess_command('timeout 60 some_command', 10.0)
            assert result == 'timeout 60 some_command'
            assert result.count('timeout') == 1

            # Complex command with existing timeout
            result = BashEnvironment.preprocess_command('timeout 30s echo test | cat', 5.0)
            assert result == 'timeout 30s echo test | cat'
            assert result.count('timeout') == 1
