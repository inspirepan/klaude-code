import signal
import subprocess
from unittest.mock import call, patch

from klaudecode.utils.bash_utils.process_management import BashProcessManager

from tests.base import BaseToolTest


class TestBashProcessManager(BaseToolTest):
    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_with_process_group_success(self, mock_getpgid, mock_killpg):
        """Test successful process group kill"""
        mock_getpgid.return_value = 12345

        BashProcessManager.kill_process_tree(12345)

        # Should call process group kill with SIGTERM then SIGKILL
        expected_calls = [call(12345, signal.SIGTERM), call(12345, signal.SIGKILL)]
        mock_killpg.assert_has_calls(expected_calls)

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_process_group_fails(self, mock_getpgid, mock_killpg):
        """Test fallback when process group kill fails"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            # Return empty to avoid infinite recursion in test
            mock_subprocess.return_value = b""

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                BashProcessManager.kill_process_tree(12345)

                # Should call pgrep to find children
                mock_subprocess.assert_called_once_with(["pgrep", "-P", "12345"], stderr=subprocess.DEVNULL, timeout=2)

                # Should kill main process
                expected_calls = [
                    call(12345, signal.SIGTERM),
                    call(12345, 0),  # Check if process exists
                    call(12345, signal.SIGKILL),  # Force kill
                ]
                mock_kill.assert_has_calls(expected_calls)

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_no_children_found(self, mock_getpgid, mock_killpg):
        """Test handling when no children are found"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.CalledProcessError(1, "pgrep")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                BashProcessManager.kill_process_tree(12345)

                # Should still try to kill main process
                mock_kill.assert_called()

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_pgrep_timeout(self, mock_getpgid, mock_killpg):
        """Test handling when pgrep times out"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.TimeoutExpired("pgrep", 2)

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                BashProcessManager.kill_process_tree(12345)

                # Should still try to kill main process despite pgrep timeout
                mock_kill.assert_called()

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_with_children(self, mock_getpgid, mock_killpg):
        """Test recursive killing of child processes"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            # Mock to return children only for the first call (parent), empty for recursive calls
            call_count = 0

            def mock_pgrep(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return b"12346\n12347\n"
                else:
                    return b""  # No children for child processes

            mock_subprocess.side_effect = mock_pgrep

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                BashProcessManager.kill_process_tree(12345)

                # Should have made calls for parent and children
                assert mock_subprocess.call_count == 3  # Parent + 2 children

                # Should have killed parent and children
                killed_pids = set()
                for call_args in mock_kill.call_args_list:
                    if call_args[0][1] == signal.SIGTERM:  # Only count SIGTERM calls
                        killed_pids.add(call_args[0][0])

                assert killed_pids >= {12345, 12346, 12347}

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_process_already_dead(self, mock_getpgid, mock_killpg):
        """Test handling when process is already dead"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.CalledProcessError(1, "pgrep")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                mock_kill.side_effect = ProcessLookupError()

                # Should not raise exception even if process is already dead
                BashProcessManager.kill_process_tree(12345)

                mock_kill.assert_called()

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_process_exists_check(self, mock_getpgid, mock_killpg):
        """Test process existence check after SIGTERM"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.CalledProcessError(1, "pgrep")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                # First call (SIGTERM) succeeds, second call (check) succeeds, third call (SIGKILL) succeeds
                mock_kill.side_effect = [None, None, None]

                BashProcessManager.kill_process_tree(12345)

                expected_calls = [
                    call(12345, signal.SIGTERM),
                    call(12345, 0),  # Check if process exists
                    call(12345, signal.SIGKILL),  # Force kill since process still exists
                ]
                mock_kill.assert_has_calls(expected_calls)

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_process_dies_after_sigterm(self, mock_getpgid, mock_killpg):
        """Test when process dies after SIGTERM and doesn't need SIGKILL"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.CalledProcessError(1, "pgrep")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                # SIGTERM succeeds, check fails (process died), SIGKILL not called
                mock_kill.side_effect = [None, ProcessLookupError()]

                BashProcessManager.kill_process_tree(12345)

                expected_calls = [
                    call(12345, signal.SIGTERM),
                    call(12345, 0),  # Check if process exists, raises ProcessLookupError
                ]
                mock_kill.assert_has_calls(expected_calls)
                assert mock_kill.call_count == 2  # Should not call SIGKILL

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    def test_kill_process_tree_last_resort_sigkill(self, mock_getpgid, mock_killpg):
        """Test last resort SIGKILL when all else fails"""
        # Simulate all methods failing and falling back to last resort
        mock_getpgid.side_effect = Exception("Unexpected error")

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = Exception("pgrep failed")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                # When getpgid fails, it jumps straight to last resort which should succeed
                mock_kill.return_value = None  # Last resort succeeds

                BashProcessManager.kill_process_tree(12345)

                # Should attempt last resort SIGKILL
                assert mock_kill.call_count == 1  # Only one call to last resort
                final_call = mock_kill.call_args_list[-1]
                assert final_call == call(12345, signal.SIGKILL)

    @patch("klaudecode.utils.bash_utils.process_management.os.killpg")
    @patch("klaudecode.utils.bash_utils.process_management.os.getpgid")
    @patch("klaudecode.utils.bash_utils.process_management.time.sleep")
    def test_kill_process_tree_timing(self, mock_sleep, mock_getpgid, mock_killpg):
        """Test that proper delays are used between kill attempts"""
        mock_getpgid.side_effect = ProcessLookupError()

        with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = subprocess.CalledProcessError(1, "pgrep")

            with patch("klaudecode.utils.bash_utils.process_management.os.kill"):
                BashProcessManager.kill_process_tree(12345)

                # Should call sleep after SIGTERM
                mock_sleep.assert_called_with(0.1)

    def test_kill_process_tree_empty_children_list(self):
        """Test handling of empty children list from pgrep"""
        with patch("klaudecode.utils.bash_utils.process_management.os.killpg") as mock_killpg:
            mock_killpg.side_effect = ProcessLookupError()

            with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
                mock_subprocess.return_value = b""  # Empty output

                with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                    BashProcessManager.kill_process_tree(12345)

                    # Should still attempt to kill the main process
                    mock_kill.assert_called()

    def test_kill_process_tree_invalid_child_pids(self):
        """Test handling of invalid child PIDs from pgrep"""
        with patch("klaudecode.utils.bash_utils.process_management.os.killpg") as mock_killpg:
            mock_killpg.side_effect = ProcessLookupError()

            with patch("klaudecode.utils.bash_utils.process_management.subprocess.check_output") as mock_subprocess:
                mock_subprocess.return_value = b"not_a_number\n\ninvalid\n"

                with patch("klaudecode.utils.bash_utils.process_management.os.kill") as mock_kill:
                    # Should not raise exception even with invalid PIDs
                    BashProcessManager.kill_process_tree(12345)

                    # Should still attempt to kill the main process
                    mock_kill.assert_called()
