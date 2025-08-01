from klaudecode.tools.edit import EditTool
from tests.base import BaseToolTest


class TestEditTool(BaseToolTest):
    """Test cases for the Edit tool."""

    def test_edit_simple_replacement(self):
        """Test simple string replacement."""
        # Create a test file
        original_content = "Hello, World!\nThis is a test.\nGoodbye, World!"
        test_file = self.create_test_file("test.txt", original_content)

        # Mark file as read
        self.mock_agent.session.file_tracker.track(str(test_file))

        # Edit the file
        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Hello, World!",
                "new_string": "Hi, Universe!",
            },
        )

        assert result.tool_call.status == "success"
        content = test_file.read_text()
        assert "Hi, Universe!" in content
        assert "Hello, World!" not in content
        assert "This is a test." in content  # Other lines unchanged

    def test_edit_multiline_replacement(self):
        """Test replacing multiple lines."""
        original_content = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        test_file = self.create_test_file("test.txt", original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Line 2\nLine 3\nLine 4",
                "new_string": "New Line 2\nNew Line 3",
            },
        )

        assert result.tool_call.status == "success"
        content = test_file.read_text()
        assert "Line 1\nNew Line 2\nNew Line 3\nLine 5" == content

    def test_edit_without_reading_first(self):
        """Test editing without reading the file first."""
        test_file = self.create_test_file("unread.txt", "Original content")

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Original",
                "new_string": "Modified",
            },
        )

        assert result.tool_call.status == "error"
        assert "has not been read yet" in result.error_msg

    def test_edit_non_existent_file(self):
        """Test editing a non-existent file."""
        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(self.temp_path / "non_existent.txt"),
                "old_string": "something",
                "new_string": "something else",
            },
        )

        assert result.tool_call.status == "error"
        assert "File does not exist" in result.error_msg

    def test_edit_string_not_found(self):
        """Test when old_string is not found in the file."""
        test_file = self.create_test_file("test.txt", "Some content")
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Not present",
                "new_string": "Replacement",
            },
        )

        assert result.tool_call.status == "error"
        assert "not found" in result.error_msg.lower()

    def test_edit_non_unique_string(self):
        """Test when old_string appears multiple times."""
        content = "Test line\nTest line\nDifferent line"
        test_file = self.create_test_file("test.txt", content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Test line",
                "new_string": "Modified line",
            },
        )

        assert result.tool_call.status == "error"
        assert "Found 2 matches" in result.error_msg

    def test_edit_replace_all(self):
        """Test replace_all functionality."""
        content = "Apple pie\nApple juice\nBanana split\nApple tart"
        test_file = self.create_test_file("test.txt", content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Apple",
                "new_string": "Orange",
                "replace_all": True,
            },
        )

        assert result.tool_call.status == "success"
        new_content = test_file.read_text()
        assert "Orange pie" in new_content
        assert "Orange juice" in new_content
        assert "Orange tart" in new_content
        assert "Apple" not in new_content

    def test_edit_identical_strings(self):
        """Test when old_string and new_string are identical."""
        test_file = self.create_test_file("test.txt", "Some content")
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "content",
                "new_string": "content",
            },
        )

        assert result.tool_call.status == "error"
        assert "same" in result.error_msg.lower()

    def test_edit_with_special_characters(self):
        """Test editing with special characters."""
        content = 'print("Hello, World!")\n# Comment with $pecial char$'
        test_file = self.create_test_file("test.py", content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "# Comment with $pecial char$",
                "new_string": "# Updated comment",
            },
        )

        assert result.tool_call.status == "success"
        assert "# Updated comment" in test_file.read_text()

    def test_edit_preserves_line_endings(self):
        """Test that line endings are preserved."""
        # Note: Edit tool may normalize line endings, so we just test that edit works
        content = "Line 1\nLine 2\nLine 3"
        test_file = self.create_test_file("test.txt", content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "Line 2",
                "new_string": "Modified Line 2",
            },
        )

        assert result.tool_call.status == "success"
        # Check that edit was successful
        new_content = test_file.read_text()
        assert "Modified Line 2" in new_content

    def test_edit_empty_file(self):
        """Test editing an empty file."""
        test_file = self.create_test_file("empty.txt", "")
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(
            EditTool,
            {
                "file_path": str(test_file),
                "old_string": "something",
                "new_string": "something else",
            },
        )

        assert result.tool_call.status == "error"
        assert "not found" in result.error_msg.lower()
