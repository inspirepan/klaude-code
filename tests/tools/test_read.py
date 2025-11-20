from klaudecode.tools.read import ReadTool

from tests.base import BaseToolTest


class TestReadTool(BaseToolTest):
    """Test cases for the Read tool."""

    def test_read_existing_file(self):
        """Test reading an existing file."""
        # Create a test file
        content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        test_file = self.create_test_file("test.txt", content)

        # Read the file
        result = self.invoke_tool(ReadTool, {"file_path": str(test_file)})

        # Check result
        assert result.tool_call.status == "success"
        assert "1→Line 1" in result.content
        assert "2→Line 2" in result.content
        assert "5→Line 5" in result.content

    def test_read_non_existent_file(self):
        """Test reading a non-existent file."""
        result = self.invoke_tool(ReadTool, {"file_path": str(self.temp_path / "non_existent.txt")})

        # Should fail with error
        assert result.tool_call.status == "error"
        assert "File does not exist" in result.error_msg

    def test_read_with_offset_and_limit(self):
        """Test reading with offset and limit."""
        # Create a file with 10 lines
        content = "\n".join([f"Line {i}" for i in range(1, 11)])
        test_file = self.create_test_file("test.txt", content)

        # Read lines 2-4 (offset seems to be 1-indexed)
        result = self.invoke_tool(
            ReadTool,
            {
                "file_path": str(test_file),
                "offset": 2,  # 1-indexed, so starts at line 2
                "limit": 3,
            },
        )

        assert result.tool_call.status == "success"
        assert "2→Line 2" in result.content
        assert "3→Line 3" in result.content
        assert "4→Line 4" in result.content
        assert "5→Line 5" not in result.content
        assert "1→Line 1" not in result.content

    def test_read_empty_file(self):
        """Test reading an empty file."""
        test_file = self.create_test_file("empty.txt", "")

        result = self.invoke_tool(ReadTool, {"file_path": str(test_file)})

        assert result.tool_call.status == "success"
        # Check content contains empty file warning
        assert "empty" in result.content.lower()

    def test_read_binary_file(self):
        """Test reading a binary file."""
        # Create a binary file
        binary_file = self.temp_path / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03")

        result = self.invoke_tool(ReadTool, {"file_path": str(binary_file)})

        # Binary files can be read, but may have strange content
        # The test should check if it doesn't crash
        assert result.tool_call.status in ["success", "error"]

    def test_read_directory(self):
        """Test reading a directory instead of a file."""
        result = self.invoke_tool(ReadTool, {"file_path": str(self.temp_path)})

        assert result.tool_call.status == "error"
        assert "EISDIR" in result.error_msg

    def test_read_with_long_lines(self):
        """Test reading file with lines longer than 2000 characters."""
        # Create a file with a very long line
        long_line = "x" * 2500
        content = f"Short line\n{long_line}\nAnother short line"
        test_file = self.create_test_file("long_lines.txt", content)

        result = self.invoke_tool(ReadTool, {"file_path": str(test_file)})

        assert result.tool_call.status == "success"
        # Long line should be truncated
        assert "x" * 2000 in result.content
        assert "x" * 2001 not in result.content

    def test_file_tracker_integration(self):
        """Test that file tracker is updated when reading."""
        content = "Test content"
        test_file = self.create_test_file("tracked.txt", content)

        # Read the file
        result = self.invoke_tool(ReadTool, {"file_path": str(test_file)})

        assert result.tool_call.status == "success"
        # Check that file was tracked
        assert str(test_file) in self.mock_agent.session.file_tracker.tracking

    def test_relative_path_conversion(self):
        """Test that relative paths are converted to absolute paths."""
        # Create a file in a subdirectory
        content = "Test content"
        subdir = self.temp_path / "subdir"
        subdir.mkdir()
        test_file = subdir / "test.txt"
        test_file.write_text(content)

        # Change working directory to temp_path
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(self.temp_path)

            # Use relative path
            result = self.invoke_tool(ReadTool, {"file_path": "subdir/test.txt"})

            assert result.tool_call.status == "success"
            assert "Test content" in result.content
        finally:
            os.chdir(original_cwd)
