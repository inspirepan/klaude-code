from klaudecode.tools.write import WriteTool
from tests.base import BaseToolTest


class TestWriteTool(BaseToolTest):
    """Test cases for the Write tool."""

    def test_write_new_file(self):
        """Test writing a new file."""
        file_path = self.temp_path / "new_file.txt"
        content = "Hello, World!\nThis is a test file."

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content}
        )

        assert result.tool_call.status == "success"
        assert file_path.exists()
        assert file_path.read_text() == content

    def test_overwrite_existing_file(self):
        """Test overwriting an existing file."""
        # Create initial file
        file_path = self.create_test_file("existing.txt", "Old content")

        # First, we need to track the file to simulate it was read
        self.mock_agent.session.file_tracker.track(str(file_path))

        # Overwrite with new content
        new_content = "New content"
        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": new_content}
        )

        assert result.tool_call.status == "success"
        assert file_path.read_text() == new_content

    def test_write_without_reading_first(self):
        """Test writing to existing file without reading it first."""
        # Create a file but don't read it
        file_path = self.create_test_file("unread.txt", "Original content")

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": "New content"}
        )

        # Should fail because file wasn't read first
        assert result.tool_call.status == "error"
        assert "has not been read yet" in result.error_msg

    def test_write_to_subdirectory(self):
        """Test writing file in a subdirectory that doesn't exist."""
        file_path = self.temp_path / "subdir" / "nested" / "file.txt"
        content = "Nested file content"

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content}
        )

        assert result.tool_call.status == "success"
        assert file_path.exists()
        assert file_path.read_text() == content

    def test_write_empty_file(self):
        """Test writing an empty file."""
        file_path = self.temp_path / "empty.txt"

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": ""}
        )

        assert result.tool_call.status == "success"
        assert file_path.exists()
        assert file_path.read_text() == ""

    def test_write_with_unicode(self):
        """Test writing file with unicode content."""
        file_path = self.temp_path / "unicode.txt"
        content = "Hello World! 🌍\nSpasibo"

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content}
        )

        assert result.tool_call.status == "success"
        assert file_path.read_text(encoding="utf-8") == content

    def test_write_to_directory(self):
        """Test writing to a directory path (should fail)."""
        result = self.invoke_tool(
            WriteTool, {"file_path": str(self.temp_path), "content": "Some content"}
        )

        assert result.tool_call.status == "error"
        # The error might be about not being read or EISDIR
        assert ("EISDIR" in result.error_msg) or (
            "has not been read" in result.error_msg
        )

    def test_file_tracker_integration(self):
        """Test that file tracker is updated after writing."""
        file_path = self.temp_path / "tracked.txt"
        content = "Tracked content"

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content}
        )

        assert result.tool_call.status == "success"
        # File should be tracked after writing
        assert str(file_path) in self.mock_agent.session.file_tracker.tracking

    def test_write_with_line_endings(self):
        """Test that line endings are preserved."""
        file_path = self.temp_path / "line_endings.txt"

        # Test with Unix line endings
        content_unix = "Line 1\nLine 2\nLine 3"
        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content_unix}
        )

        assert result.tool_call.status == "success"
        assert file_path.read_bytes() == content_unix.encode("utf-8")

    def test_write_large_file(self):
        """Test writing a large file."""
        file_path = self.temp_path / "large.txt"
        # Create 1MB of content
        content = "x" * (1024 * 1024)

        result = self.invoke_tool(
            WriteTool, {"file_path": str(file_path), "content": content}
        )

        assert result.tool_call.status == "success"
        assert file_path.stat().st_size == len(content)

    def test_relative_path_conversion(self):
        """Test that relative paths are converted to absolute paths."""
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(self.temp_path)

            # Use relative path
            result = self.invoke_tool(
                WriteTool,
                {"file_path": "relative.txt", "content": "Relative path content"},
            )

            assert result.tool_call.status == "success"
            assert (self.temp_path / "relative.txt").exists()
        finally:
            os.chdir(original_cwd)
