from unittest.mock import Mock, patch

from klaudecode.utils.bash_utils.output_processing import BashOutputProcessor
from tests.base import BaseToolTest


class TestBashOutputProcessor(BaseToolTest):
    def test_format_output_without_truncation(self):
        """Test output formatting when no truncation is needed"""
        output_lines = ['Line 1', 'Line 2', 'Line 3']
        total_size = 100  # Small size, no truncation needed

        result = BashOutputProcessor.format_output_with_truncation(output_lines, total_size)

        assert result == 'Line 1\nLine 2\nLine 3'

    def test_format_output_with_truncation(self):
        """Test output formatting with middle truncation"""
        # Create many lines to trigger truncation
        output_lines = [f'Line {i}' for i in range(500)]
        total_size = 50000  # Large size to trigger truncation

        result = BashOutputProcessor.format_output_with_truncation(output_lines, total_size)

        # Should contain first 200 lines
        assert 'Line 0' in result
        assert 'Line 199' in result

        # Should contain last 200 lines
        assert 'Line 300' in result  # Last 200 start at index 300
        assert 'Line 499' in result

        # Should contain truncation message
        assert 'truncated from middle' in result
        assert '100 lines' in result  # 500 - 2*200 = 100 truncated lines

    def test_format_output_edge_case_exact_limit(self):
        """Test output formatting at exact truncation threshold"""
        # Exactly 400 lines (2 * TRUNCATE_PRESERVE_LINES)
        output_lines = [f'Line {i}' for i in range(400)]
        total_size = 25000  # Below MAX_OUTPUT_SIZE

        result = BashOutputProcessor.format_output_with_truncation(output_lines, total_size)

        # Should not truncate
        assert 'Line 0' in result
        assert 'Line 399' in result
        assert 'truncated' not in result

    def test_process_output_line_normal(self):
        """Test processing a normal output line"""
        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break = BashOutputProcessor.process_output_line('Normal line\n', output_lines, total_size, update_func)

        assert output_lines == ['Normal line']
        assert new_size == 12  # len('Normal line') + 1
        assert should_break is False
        update_func.assert_called_once()

    def test_process_output_line_with_ansi_codes(self):
        """Test processing line with ANSI escape codes"""
        output_lines = []
        total_size = 0
        update_func = Mock()

        with patch('klaudecode.utils.bash_utils.output_processing.BashEnvironment.strip_ansi_codes') as mock_strip:
            mock_strip.return_value = 'Clean line'

            new_size, should_break = BashOutputProcessor.process_output_line('\x1b[31mRed text\x1b[0m\n', output_lines, total_size, update_func)

            mock_strip.assert_called_once_with('\x1b[31mRed text\x1b[0m')
            assert output_lines == ['Clean line']

    def test_process_output_line_interactive_prompt(self):
        """Test processing line with interactive prompt"""
        output_lines = []
        total_size = 0
        update_func = Mock()

        with patch('klaudecode.utils.bash_utils.output_processing.BashInteractionDetector.detect_interactive_prompt') as mock_detect:
            mock_detect.return_value = True

            new_size, should_break = BashOutputProcessor.process_output_line('Enter password:', output_lines, total_size, update_func)

            assert should_break is True
            assert 'Interactive prompt detected' in output_lines[0]
            assert 'Command terminated' in output_lines[1]
            assert update_func.call_count == 1

    def test_process_output_line_safe_continue_prompt(self):
        """Test processing line with safe continue prompt"""
        output_lines = []
        total_size = 0
        update_func = Mock()

        with patch('klaudecode.utils.bash_utils.output_processing.BashInteractionDetector.detect_interactive_prompt') as mock_detect_interactive:
            with patch('klaudecode.utils.bash_utils.output_processing.BashInteractionDetector.detect_safe_continue_prompt') as mock_detect_safe:
                mock_detect_interactive.return_value = False
                mock_detect_safe.return_value = True

                new_size, should_break = BashOutputProcessor.process_output_line('Press enter to continue', output_lines, total_size, update_func)

                assert should_break is False
                assert 'Safe continue prompt detected' in output_lines[0]
                assert 'Press enter to continue' in output_lines[1]

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'linux')
    @patch('klaudecode.utils.bash_utils.output_processing.select.select')
    def test_read_process_output_unix_with_data(self, mock_select):
        """Test reading process output on Unix with available data"""
        mock_process = Mock()
        mock_process.stdout.readline.return_value = 'Test line\n'
        mock_select.return_value = ([mock_process.stdout], [], [])

        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func)

        mock_select.assert_called_once_with([mock_process.stdout], [], [], 0.05)
        assert new_size > total_size
        assert should_break is False
        assert error == ''

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'linux')
    @patch('klaudecode.utils.bash_utils.output_processing.select.select')
    @patch('klaudecode.utils.bash_utils.output_processing.time.sleep')
    def test_read_process_output_unix_no_data(self, mock_sleep, mock_select):
        """Test reading process output on Unix with no available data"""
        mock_process = Mock()
        mock_select.return_value = ([], [], [])  # No data available

        output_lines = []
        total_size = 0
        update_func = Mock()
        check_canceled = Mock(return_value=False)

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func, check_canceled)

        assert new_size == total_size
        assert should_break is False
        assert error == ''
        mock_sleep.assert_called_once_with(0.005)

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'linux')
    @patch('klaudecode.utils.bash_utils.output_processing.select.select')
    def test_read_process_output_unix_canceled(self, mock_select):
        """Test reading process output when canceled"""
        mock_process = Mock()
        mock_select.return_value = ([], [], [])  # No data available

        output_lines = []
        total_size = 0
        update_func = Mock()
        check_canceled = Mock(return_value=True)

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func, check_canceled)

        assert should_break is True
        assert error == ''

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'linux')
    @patch('klaudecode.utils.bash_utils.output_processing.select.select')
    def test_read_process_output_unix_exception(self, mock_select):
        """Test handling of exceptions during Unix output reading"""
        mock_process = Mock()
        mock_process.stdout.readline.side_effect = Exception('Read error')
        mock_select.return_value = ([mock_process.stdout], [], [])

        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func)

        assert should_break is True
        assert 'Error reading output' in error
        assert 'Read error' in error

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'win32')
    @patch('klaudecode.utils.bash_utils.output_processing.time.sleep')
    def test_read_process_output_windows_with_data(self, mock_sleep):
        """Test reading process output on Windows with data"""
        mock_process = Mock()
        mock_process.stdout.readline.return_value = 'Windows line\n'

        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func)

        assert new_size > total_size
        assert should_break is False
        assert error == ''
        mock_sleep.assert_not_called()

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'win32')
    @patch('klaudecode.utils.bash_utils.output_processing.time.sleep')
    def test_read_process_output_windows_no_data(self, mock_sleep):
        """Test reading process output on Windows with no data"""
        mock_process = Mock()
        mock_process.stdout.readline.return_value = ''  # No data

        output_lines = []
        total_size = 0
        update_func = Mock()
        check_canceled = Mock(return_value=False)

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func, check_canceled)

        assert new_size == total_size
        assert should_break is False
        assert error == ''
        mock_sleep.assert_called_once_with(0.005)

    @patch('klaudecode.utils.bash_utils.output_processing.sys.platform', 'win32')
    def test_read_process_output_windows_exception(self):
        """Test handling of exceptions during Windows output reading"""
        mock_process = Mock()
        mock_process.stdout.readline.side_effect = Exception('Windows read error')

        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break, error = BashOutputProcessor.read_process_output(mock_process, output_lines, total_size, update_func)

        assert should_break is True
        assert 'Error reading output' in error
        assert 'Windows read error' in error

    def test_output_constants(self):
        """Test that output processing constants are set correctly"""
        assert BashOutputProcessor.MAX_OUTPUT_SIZE == 30000
        assert BashOutputProcessor.TRUNCATE_PRESERVE_LINES == 200

    def test_format_output_truncation_calculation(self):
        """Test truncation calculation accuracy"""
        # Create exactly enough lines to trigger truncation
        preserve_lines = BashOutputProcessor.TRUNCATE_PRESERVE_LINES
        total_lines = preserve_lines * 2 + 50  # 450 lines total
        output_lines = [f'Line {i}' for i in range(total_lines)]
        total_size = 35000  # Above MAX_OUTPUT_SIZE

        result = BashOutputProcessor.format_output_with_truncation(output_lines, total_size)

        # Should mention correct number of truncated lines
        assert '50 lines' in result  # 450 - 2*200 = 50

        # Calculate expected truncated characters
        start_lines = output_lines[:preserve_lines]
        end_lines = output_lines[-preserve_lines:]
        start_chars = sum(len(line) + 1 for line in start_lines)
        end_chars = sum(len(line) + 1 for line in end_lines)
        expected_truncated_chars = total_size - start_chars - end_chars

        assert f'{expected_truncated_chars} chars' in result

    def test_process_output_line_carriage_return_handling(self):
        """Test that carriage returns are properly stripped"""
        output_lines = []
        total_size = 0
        update_func = Mock()

        new_size, should_break = BashOutputProcessor.process_output_line('Line with CR\r\n', output_lines, total_size, update_func)

        assert output_lines == ['Line with CR']
        assert '\r' not in output_lines[0]
        assert '\n' not in output_lines[0]
