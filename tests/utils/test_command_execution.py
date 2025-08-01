from unittest.mock import Mock, patch

from klaudecode.utils.bash_utils.command_execution import BashCommandExecutor
from tests.base import BaseToolTest


class TestBashCommandExecutor(BaseToolTest):
    def test_default_timeout_constants(self):
        """Test timeout constants are set correctly"""
        assert BashCommandExecutor.DEFAULT_TIMEOUT == 300000  # 5 minutes
        assert BashCommandExecutor.MAX_TIMEOUT == 600000  # 10 minutes

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    @patch(
        "klaudecode.utils.bash_utils.command_execution.BashEnvironment.preprocess_command"
    )
    @patch(
        "klaudecode.utils.bash_utils.command_execution.BashEnvironment.get_non_interactive_env"
    )
    def test_successful_command_execution(self, mock_env, mock_preprocess, mock_popen):
        """Test successful command execution"""
        # Setup mocks
        mock_env.return_value = {"TEST": "1"}
        mock_preprocess.return_value = "echo test"

        mock_process = Mock()
        mock_process.poll.side_effect = [
            None,
            None,
            0,
        ]  # Running, running, then finished
        mock_process.stdout.read.return_value = "test output\n"
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        # Mock output processing
        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
        ) as mock_read:
            mock_read.return_value = (100, True, "")  # total_size, should_break, error

            check_canceled = Mock(return_value=False)
            update_content = Mock()

            result = BashCommandExecutor.execute_bash_command(
                command="echo test",
                timeout_seconds=30.0,
                check_canceled=check_canceled,
                update_content=update_content,
            )

            assert result == ""  # No error
            mock_preprocess.assert_called_once_with("echo test", 30.0)
            mock_popen.assert_called_once()

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    @patch(
        "klaudecode.utils.bash_utils.command_execution.BashEnvironment.preprocess_command"
    )
    def test_command_timeout(self, mock_preprocess, mock_popen):
        """Test command timeout handling"""
        mock_preprocess.return_value = "sleep 10"

        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345
        # Mock stdout to avoid select issues
        mock_process.stdout = Mock()
        mock_process.stdout.fileno.return_value = 1
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.time.time"
        ) as mock_time:
            # Simulate time progression to trigger timeout
            mock_time.side_effect = [0, 5, 10, 35]  # Start, check1, check2, timeout

            with patch(
                "klaudecode.utils.bash_utils.command_execution.BashProcessManager.kill_process_tree"
            ) as mock_kill:
                with patch(
                    "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
                ) as mock_read:
                    mock_read.return_value = (0, False, "")  # No error initially

                    check_canceled = Mock(return_value=False)
                    update_content = Mock()

                    result = BashCommandExecutor.execute_bash_command(
                        command="sleep 10",
                        timeout_seconds=30.0,
                        check_canceled=check_canceled,
                        update_content=update_content,
                    )

                    assert result == ""  # No error returned for timeout
                    # Process might be killed twice - once by timeout, once by cleanup
                    assert mock_kill.call_count >= 1
                    mock_kill.assert_any_call(12345)

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    def test_command_cancellation(self, mock_popen):
        """Test command cancellation by user"""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345
        # Mock stdout to avoid select issues
        mock_process.stdout = Mock()
        mock_process.stdout.fileno.return_value = 1
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashProcessManager.kill_process_tree"
        ) as mock_kill:
            with patch(
                "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
            ) as mock_read:
                mock_read.return_value = (0, False, "")

                check_canceled = Mock(
                    side_effect=[False, False, True]
                )  # Cancel on third check
                update_content = Mock()

                result = BashCommandExecutor.execute_bash_command(
                    command="sleep 60",
                    timeout_seconds=120.0,
                    check_canceled=check_canceled,
                    update_content=update_content,
                )

                assert result == ""  # No error
                # Process might be killed twice - once by cancellation, once by cleanup
                assert mock_kill.call_count >= 1
                mock_kill.assert_any_call(12345)

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    def test_command_with_non_zero_exit_code(self, mock_popen):
        """Test command with non-zero exit code"""
        mock_process = Mock()
        mock_process.poll.side_effect = [
            None,
            1,
            1,
        ]  # Running, then finished with exit code 1
        mock_process.stdout.read.return_value = "error output\n"
        mock_process.returncode = 1
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
        ) as mock_read:
            mock_read.return_value = (100, True, "")

            check_canceled = Mock(return_value=False)
            update_content = Mock()

            result = BashCommandExecutor.execute_bash_command(
                command="false",
                timeout_seconds=30.0,
                check_canceled=check_canceled,
                update_content=update_content,
            )

            assert result == ""  # Still no error returned

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    def test_process_exception_handling(self, mock_popen):
        """Test handling of process creation exceptions"""
        mock_popen.side_effect = OSError("Process creation failed")

        check_canceled = Mock(return_value=False)
        update_content = Mock()

        result = BashCommandExecutor.execute_bash_command(
            command="invalid_command",
            timeout_seconds=30.0,
            check_canceled=check_canceled,
            update_content=update_content,
        )

        assert "Error executing command" in result
        assert "Process creation failed" in result

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    def test_output_processing_error(self, mock_popen):
        """Test handling of output processing errors"""
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
        ) as mock_read:
            mock_read.return_value = (100, True, "Output processing error")

            check_canceled = Mock(return_value=False)
            update_content = Mock()

            result = BashCommandExecutor.execute_bash_command(
                command="echo test",
                timeout_seconds=30.0,
                check_canceled=check_canceled,
                update_content=update_content,
            )

            assert result == "Output processing error"

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    @patch(
        "klaudecode.utils.bash_utils.command_execution.BashEnvironment.get_non_interactive_env"
    )
    def test_environment_setup(self, mock_env, mock_popen):
        """Test that environment is set up correctly"""
        mock_env.return_value = {"NONINTERACTIVE": "1", "CI": "true"}

        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0, 0]
        mock_process.stdout.read.return_value = ""
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
        ) as mock_read:
            mock_read.return_value = (0, True, "")

            check_canceled = Mock(return_value=False)
            update_content = Mock()

            BashCommandExecutor.execute_bash_command(
                command="echo test",
                timeout_seconds=30.0,
                check_canceled=check_canceled,
                update_content=update_content,
            )

            # Verify Popen was called with correct environment
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            env_passed = call_args.kwargs["env"]
            assert "NONINTERACTIVE" in env_passed
            assert env_passed["NONINTERACTIVE"] == "1"

    @patch("klaudecode.utils.bash_utils.command_execution.subprocess.Popen")
    def test_process_cleanup_on_exception(self, mock_popen):
        """Test that process is cleaned up when exception occurs"""
        mock_process = Mock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345
        mock_popen.return_value = mock_process

        with patch(
            "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
        ) as mock_read:
            mock_read.side_effect = Exception("Processing error")

            with patch(
                "klaudecode.utils.bash_utils.command_execution.BashProcessManager.kill_process_tree"
            ) as mock_kill:
                check_canceled = Mock(return_value=False)
                update_content = Mock()

                result = BashCommandExecutor.execute_bash_command(
                    command="echo test",
                    timeout_seconds=30.0,
                    check_canceled=check_canceled,
                    update_content=update_content,
                )

                assert "Error executing command" in result
                mock_kill.assert_called_once_with(12345)

    def test_update_content_callback(self):
        """Test that update_content callback is called correctly"""
        with patch(
            "klaudecode.utils.bash_utils.command_execution.subprocess.Popen"
        ) as mock_popen:
            mock_process = Mock()
            mock_process.poll.side_effect = [None, 0, 0]
            mock_process.stdout.read.return_value = "test output"
            mock_process.returncode = 0
            mock_popen.return_value = mock_process

            with patch(
                "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.read_process_output"
            ) as mock_read:
                mock_read.return_value = (100, True, "")

                with patch(
                    "klaudecode.utils.bash_utils.command_execution.BashOutputProcessor.format_output_with_truncation"
                ) as mock_format:
                    mock_format.return_value = "formatted output"

                    check_canceled = Mock(return_value=False)
                    update_content = Mock()

                    BashCommandExecutor.execute_bash_command(
                        command="echo test",
                        timeout_seconds=30.0,
                        check_canceled=check_canceled,
                        update_content=update_content,
                    )

                    # Verify update_content was called
                    assert update_content.call_count >= 1
                    update_content.assert_called_with("formatted output")
