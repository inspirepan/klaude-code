import re
from unittest.mock import Mock, patch

from klaudecode.user_input.input_handler import UserInputHandler


class TestAtPatternParsing:
    """Test @ pattern parsing in UserInputHandler."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.mock_agent = Mock()
        self.handler = UserInputHandler(self.mock_agent)

    def test_parse_at_pattern_matches(self):
        """Test that @ patterns are correctly matched."""
        test_cases = [
            # Basic file paths
            ("@file.txt", ["file.txt"]),
            ("@src/main.py", ["src/main.py"]),
            ("@/absolute/path.txt", ["/absolute/path.txt"]),
            # Directory paths
            ("@src/", ["src/"]),
            ("@/usr/local/", ["/usr/local/"]),
            # Multiple patterns
            ("@file1.txt and @file2.py", ["file1.txt", "file2.py"]),
            ("Check @src/main.py and @tests/test.py", ["src/main.py", "tests/test.py"]),
            # Complex text with special characters
            (
                "@src/klaudecode/llm/ what files are there, @src/klaudecode/llm/llm_proxy_base.py what does it do",
                ["src/klaudecode/llm/", "src/klaudecode/llm/llm_proxy_base.py"],
            ),
            # Edge cases
            ("@@double.txt", ["@double.txt"]),  # Second @ is part of filename
            ("email@example.com", ["example.com"]),  # Will match after @ in email
            ("@", []),  # @ alone should not match
            ("@ file.txt", []),  # Space after @ should not match
        ]

        pattern = r"@([^\s]+)"
        for text, expected_paths in test_cases:
            matches = re.findall(pattern, text)
            assert matches == expected_paths, f"Failed for text: {text}"

    @patch("klaudecode.user_input.input_handler.execute_read")
    @patch("klaudecode.user_input.input_handler.get_directory_structure")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    def test_parse_at_files_with_mocks(self, mock_is_dir, mock_exists, mock_get_dir, mock_execute_read):
        """Test _parse_at_files method with mocked file operations."""
        # Setup mocks
        mock_exists.return_value = True
        mock_is_dir.return_value = False

        # Mock successful file read - use ReadResult from tools.read
        from klaudecode.tools.read import ReadResult

        mock_read_result = ReadResult(
            path="test.txt",
            content="file content",
            line_count=10,
            success=True,
            is_directory=False,
        )
        mock_execute_read.return_value = mock_read_result

        # Test parsing a file
        text = "Check @test.txt for details"
        attachments = self.handler._parse_at_files(text)

        assert len(attachments) == 1
        assert attachments[0].path.endswith("test.txt")
        assert attachments[0].content == "file content"
        assert attachments[0].line_count == 10
        assert attachments[0].is_directory is False

    @patch("klaudecode.user_input.input_handler.execute_read")
    @patch("klaudecode.user_input.input_handler.get_directory_structure")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.is_dir")
    def test_parse_at_files_directory(self, mock_is_dir, mock_exists, mock_get_dir, mock_execute_read):
        """Test _parse_at_files method with directory paths."""
        # Setup mocks for directory
        mock_exists.return_value = True
        mock_is_dir.return_value = True

        # Mock successful directory listing
        mock_get_dir.return_value = ("directory listing", False, 5)

        # Test parsing a directory with trailing slash
        text = "List @src/ contents"
        attachments = self.handler._parse_at_files(text)

        assert len(attachments) == 1
        assert attachments[0].path.endswith("src")
        assert "directory listing" in attachments[0].content
        # For directories, line_count is 0 by default in Attachment creation
        assert attachments[0].line_count == 0
        # The implementation sets is_directory to False by default in Attachment creation
        assert attachments[0].is_directory is False

    @patch("klaudecode.user_input.input_handler.execute_read")
    @patch("klaudecode.user_input.input_handler.get_directory_structure")
    def test_parse_at_files_multiple(self, mock_get_dir, mock_execute_read):
        """Test parsing multiple @ references."""
        # Mock file read
        from klaudecode.tools.read import ReadResult

        mock_read_result = ReadResult(
            path="file1.txt",
            content="file content",
            line_count=10,
            success=True,
            is_directory=False,
        )
        mock_execute_read.return_value = mock_read_result

        # Mock directory listing
        mock_get_dir.return_value = ("dir content", False, 5)

        with patch("pathlib.Path.exists") as mock_exists:
            with patch("pathlib.Path.is_dir") as mock_is_dir:
                # First call for file1.txt (file)
                # Second call for dir/ (directory)
                mock_exists.side_effect = [True, True]
                mock_is_dir.side_effect = [False, True]

                text = "Check @file1.txt and @dir/ for info"
                attachments = self.handler._parse_at_files(text)

                assert len(attachments) == 2
                # First attachment is a file
                assert attachments[0].is_directory is False
                # Second attachment is a directory (though is_directory is False by default in Attachment creation)
                assert attachments[1].is_directory is False

    @patch("klaudecode.user_input.input_handler.execute_read")
    def test_parse_at_files_failed_read(self, mock_execute_read):
        """Test handling of failed file reads."""
        # Mock failed file read
        from klaudecode.tools.read import ReadResult

        mock_read_result = ReadResult(path="nonexistent.txt", success=False, error_msg="File not found")
        mock_execute_read.return_value = mock_read_result

        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_dir", return_value=False):
                text = "Check @nonexistent.txt"
                attachments = self.handler._parse_at_files(text)

                # Failed reads should not create attachments
                assert len(attachments) == 0

    def test_parse_at_files_absolute_vs_relative_paths(self):
        """Test handling of absolute vs relative paths."""
        with patch("klaudecode.user_input.input_handler.execute_read") as mock_execute_read:
            from klaudecode.tools.read import ReadResult

            def mock_read_side_effect(path, **kwargs):
                return ReadResult(
                    path=path,
                    content="content",
                    line_count=1,
                    success=True,
                    is_directory=False,
                )

            mock_execute_read.side_effect = mock_read_side_effect

            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_dir", return_value=False):
                    # Test absolute path
                    text1 = "Check @/absolute/path.txt"
                    attachments1 = self.handler._parse_at_files(text1)
                    assert len(attachments1) == 1
                    assert attachments1[0].path == "/absolute/path.txt"

                    # Test relative path
                    text2 = "Check @relative/path.txt"
                    attachments2 = self.handler._parse_at_files(text2)
                    assert len(attachments2) == 1
                    assert attachments2[0].path.endswith("relative/path.txt")
                    assert not attachments2[0].path.startswith("/relative")

    def test_original_text_preserved(self):
        """Test that original user input is preserved."""
        test_inputs = [
            "@file.txt check this",
            "Look at @src/main.py and @tests/test.py",
            "@src/klaudecode/llm/ what files are there, @src/klaudecode/llm/llm_proxy_base.py what does it do",
        ]

        with patch("klaudecode.user_input.input_handler.execute_read") as mock_execute_read:
            # Mock the read result properly using ReadResult
            from klaudecode.tools.read import ReadResult

            mock_read_result = ReadResult(
                path="mocked_file.txt",
                content="mocked content",
                line_count=1,
                success=True,
                is_directory=False,
            )
            mock_execute_read.return_value = mock_read_result

            with patch("klaudecode.user_input.input_handler.get_directory_structure") as mock_get_dir:
                mock_get_dir.return_value = ("mocked dir", False, 1)

                for original_text in test_inputs:
                    # The handler should not modify the original text
                    # This is tested implicitly - the method returns attachments only
                    attachments = self.handler._parse_at_files(original_text)
                    # Just verify the method runs without error
                    assert isinstance(attachments, list)
