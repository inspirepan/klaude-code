from unittest.mock import Mock, patch

from klaudecode.tools.bash import BashTool
from tests.base import BaseToolTest


class TestBashTool(BaseToolTest):
    def test_successful_command(self):
        """Test executing a successful command"""
        result = self.invoke_tool(BashTool, {'command': 'echo "Hello World"', 'description': 'Test echo command'})

        assert result.tool_call.status == 'success'
        assert 'Hello World' in result.content

    def test_command_with_description(self):
        """Test command execution with description"""
        result = self.invoke_tool(BashTool, {'command': 'ls', 'description': 'List files in directory', 'timeout': 5000})

        assert result.tool_call.status == 'success'

    def test_command_timeout(self):
        """Test command timeout functionality"""
        with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
            mock_execute.return_value = 'Command timed out after 1.0 seconds'

            result = self.invoke_tool(BashTool, {'command': 'sleep 10', 'timeout': 1000})

            assert result.tool_call.status == 'error'
            assert 'timed out' in result.error_msg

    def test_dangerous_command_blocked(self):
        """Test that dangerous commands are blocked"""
        result = self.invoke_tool(BashTool, {'command': 'rm -rf /'})

        assert result.tool_call.status == 'error'
        assert 'Dangerous command detected' in result.error_msg

    def test_specialized_tool_suggestion(self):
        """Test that specialized tool suggestions are provided"""
        with patch('klaudecode.utils.bash_utils.security.BashSecurity.validate_command_safety') as mock_validate:
            mock_validate.return_value = (True, "<system-reminder>Command 'ls' detected. Use LS tool instead of ls command</system-reminder>")

            with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
                mock_execute.return_value = ''

                result = self.invoke_tool(BashTool, {'command': 'ls'})

                assert result.tool_call.status == 'success'
                assert len(result.system_reminders) > 0
                assert 'Use LS tool instead' in result.system_reminders[0]

    def test_command_execution_error(self):
        """Test handling of command execution errors"""
        with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
            mock_execute.return_value = 'Command execution failed with error'

            result = self.invoke_tool(BashTool, {'command': 'invalid_command_xyz'})

            assert result.tool_call.status == 'error'
            assert 'Command execution failed' in result.error_msg

    def test_max_timeout_enforcement(self):
        """Test that timeout is capped at maximum value"""
        with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
            mock_execute.return_value = ''

            result = self.invoke_tool(
                BashTool,
                {
                    'command': 'echo test',
                    'timeout': 700000,  # Over max timeout
                },
            )

            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            timeout_seconds = call_args.kwargs['timeout_seconds']
            assert timeout_seconds == 600.0  # Should be capped at 600 seconds

    def test_default_timeout(self):
        """Test that default timeout is used when not specified"""
        with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
            mock_execute.return_value = ''

            result = self.invoke_tool(BashTool, {'command': 'echo test'})

            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            timeout_seconds = call_args.kwargs['timeout_seconds']
            assert timeout_seconds == 300.0  # Default 5 minutes

    def test_interrupt_handling(self):
        """Test that command can be interrupted"""
        mock_instance = Mock()
        mock_instance.tool_result.return_value.tool_call.status = 'canceled'
        mock_instance.check_interrupt.return_value = True

        with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:

            def check_canceled_callback():
                return mock_instance.tool_result().tool_call.status == 'canceled'

            mock_execute.side_effect = lambda **kwargs: kwargs['check_canceled']()

            result = self.invoke_tool(BashTool, {'command': 'sleep 60'})

    def test_empty_description(self):
        """Test that empty description is handled properly"""
        result = self.invoke_tool(BashTool, {'command': 'echo test'})

        assert result.tool_call.status == 'success'

    def test_command_validation_called(self):
        """Test that security validation is called"""
        with patch('klaudecode.utils.bash_utils.security.BashSecurity.validate_command_safety') as mock_validate:
            mock_validate.return_value = (True, '')

            with patch('klaudecode.utils.bash_utils.command_execution.BashCommandExecutor.execute_bash_command') as mock_execute:
                mock_execute.return_value = ''

                self.invoke_tool(BashTool, {'command': 'echo test'})

                mock_validate.assert_called_once_with('echo test')

    def test_parallelable_property(self):
        """Test that BashTool is not parallelable"""
        assert BashTool.parallelable is False
