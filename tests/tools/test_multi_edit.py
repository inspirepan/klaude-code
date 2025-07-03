"""Unit tests for the MultiEdit tool."""

from unittest.mock import patch


from klaudecode.tools import MultiEditTool as MultiEdit
from tests.base import BaseToolTest


class TestMultiEditBase:
    """Base test class with test cases for the MultiEdit tool."""

    __test__ = False  # Don't collect this base class for testing

    def test_multi_edit_simple_replacements(self):
        """Test simple sequential replacements."""
        original_content = 'Hello, World!\nThis is a test.\nGoodbye, World!'
        test_file = self.create_test_file('test.txt', original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'Hello, World!', 'new_string': 'Hi, Universe!'}, {'old_string': 'Goodbye, World!', 'new_string': 'See you later, Universe!'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        content = test_file.read_text()
        assert 'Hi, Universe!' in content
        assert 'See you later, Universe!' in content
        assert 'This is a test.' in content
        assert 'Hello, World!' not in content
        assert 'Goodbye, World!' not in content

    def test_multi_edit_sequential_dependencies(self):
        """Test edits that depend on previous edits."""
        original_content = 'apple pie\napple juice\napple tart'
        test_file = self.create_test_file('test.txt', original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'apple', 'new_string': 'orange', 'replace_all': True}, {'old_string': 'orange pie', 'new_string': 'lemon pie'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        content = test_file.read_text()
        assert 'lemon pie' in content
        assert 'orange juice' in content
        assert 'orange tart' in content
        assert 'apple' not in content

    def test_multi_edit_multiline_replacements(self):
        """Test replacing multiple lines in sequence."""
        original_content = 'Line 1\nLine 2\nLine 3\nLine 4\nLine 5'
        test_file = self.create_test_file('test.txt', original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'Line 1\nLine 2', 'new_string': 'First Line\nSecond Line'}, {'old_string': 'Line 4\nLine 5', 'new_string': 'Fourth Line\nFifth Line'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        content = test_file.read_text()
        assert content == 'First Line\nSecond Line\nLine 3\nFourth Line\nFifth Line'

    def test_multi_edit_empty_edits_list(self):
        """Test with empty edits list."""
        test_file = self.create_test_file('test.txt', 'Some content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': []})

        assert result.tool_call.status == 'error'
        assert 'edits list cannot be empty' in result.error_msg

    def test_multi_edit_without_reading_first(self):
        """Test editing without reading the file first."""
        test_file = self.create_test_file('unread.txt', 'Original content')

        edits = [{'old_string': 'Original', 'new_string': 'Modified'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'has not been read yet' in result.error_msg

    def test_multi_edit_non_existent_file(self):
        """Test editing a non-existent file."""
        edits = [{'old_string': 'something', 'new_string': 'something else'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(self.temp_path / 'non_existent.txt'), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'File does not exist' in result.error_msg

    def test_multi_edit_string_not_found(self):
        """Test when old_string is not found in the file."""
        test_file = self.create_test_file('test.txt', 'Some content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'Some content', 'new_string': 'Modified content'}, {'old_string': 'Not present', 'new_string': 'Replacement'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Edit 2' in result.error_msg
        assert 'not found' in result.error_msg.lower()

    def test_multi_edit_non_unique_without_replace_all(self):
        """Test when old_string appears multiple times without replace_all."""
        content = 'Test line\nTest line\nDifferent line'
        test_file = self.create_test_file('test.txt', content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'Test line', 'new_string': 'Modified line'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Found 2 matches' in result.error_msg
        assert 'replace_all' in result.error_msg

    def test_multi_edit_replace_all_multiple_edits(self):
        """Test replace_all functionality across multiple edits."""
        content = 'Apple pie\nApple juice\nBanana split\nApple tart'
        test_file = self.create_test_file('test.txt', content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [
            {'old_string': 'Apple', 'new_string': 'Orange', 'replace_all': True},
            {'old_string': 'Banana', 'new_string': 'Mango'},
            {'old_string': 'split', 'new_string': 'smoothie'},
        ]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        new_content = test_file.read_text()
        assert 'Orange pie' in new_content
        assert 'Orange juice' in new_content
        assert 'Orange tart' in new_content
        assert 'Mango smoothie' in new_content
        assert 'Apple' not in new_content
        assert 'Banana split' not in new_content

    def test_multi_edit_identical_strings(self):
        """Test when old_string and new_string are identical."""
        test_file = self.create_test_file('test.txt', 'Some content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [
            {'old_string': 'Some', 'new_string': 'Another'},
            {'old_string': 'content', 'new_string': 'content'},  # Identical
        ]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Edit 2' in result.error_msg
        assert 'same' in result.error_msg.lower()

    def test_multi_edit_with_special_characters(self):
        """Test editing with special characters."""
        content = 'print("Hello, World!")\n# Comment with $pecial char$\nregex: [a-z]+'
        test_file = self.create_test_file('test.py', content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': '# Comment with $pecial char$', 'new_string': '# Updated comment'}, {'old_string': 'regex: [a-z]+', 'new_string': 'pattern: [A-Z]+'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        new_content = test_file.read_text()
        assert '# Updated comment' in new_content
        assert 'pattern: [A-Z]+' in new_content

    def test_multi_edit_conflicting_edits(self):
        """Test edits that would conflict with each other."""
        content = 'The quick brown fox jumps over the lazy dog'
        test_file = self.create_test_file('test.txt', content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [
            {'old_string': 'quick brown fox', 'new_string': 'slow red fox'},
            {'old_string': 'brown', 'new_string': 'green'},  # This should fail as 'brown' is already replaced
        ]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Edit 2' in result.error_msg
        assert 'not found' in result.error_msg.lower()

    def test_multi_edit_empty_file(self):
        """Test editing an empty file."""
        test_file = self.create_test_file('empty.txt', '')
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'something', 'new_string': 'something else'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'not found' in result.error_msg.lower()

    def test_multi_edit_rollback_on_failure(self):
        """Test that changes are rolled back if any edit fails."""
        original_content = 'Line 1\nLine 2\nLine 3'
        test_file = self.create_test_file('test.txt', original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [
            {'old_string': 'Line 1', 'new_string': 'Modified Line 1'},
            {'old_string': 'Line 2', 'new_string': 'Modified Line 2'},
            {'old_string': 'Not Present', 'new_string': 'This will fail'},
        ]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        # Check that file content is unchanged (rollback worked)
        assert test_file.read_text() == original_content

    def test_multi_edit_empty_old_string(self):
        """Test with empty old_string."""
        test_file = self.create_test_file('test.txt', 'Some content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        edits = [{'old_string': 'Some', 'new_string': 'Another'}, {'old_string': '', 'new_string': 'Invalid'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Edit 2' in result.error_msg
        assert 'cannot be empty' in result.error_msg

    def test_multi_edit_create_new_file(self):
        """Test creating a new file with MultiEdit."""
        new_file = self.temp_path / 'new_file.txt'

        # Track the file path even though it doesn't exist yet
        self.mock_agent.session.file_tracker.track(str(new_file))

        edits = [{'old_string': '', 'new_string': 'This is new content\nOn multiple lines'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(new_file), 'edits': edits})

        # This should fail because the file doesn't exist
        assert result.tool_call.status == 'error'
        assert 'File does not exist' in result.error_msg

    def test_multi_edit_large_number_of_edits(self):
        """Test with a large number of sequential edits."""
        # Create content with numbered lines
        lines = [f'Line {i:02d}' for i in range(1, 21)]  # Use zero-padded numbers
        original_content = '\n'.join(lines)
        test_file = self.create_test_file('test.txt', original_content)
        self.mock_agent.session.file_tracker.track(str(test_file))

        # Create edits for even numbered lines
        edits = []
        for i in range(2, 21, 2):
            edits.append({'old_string': f'Line {i:02d}', 'new_string': f'Modified Line {i:02d}'})

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'success'
        content = test_file.read_text()

        # Check that even lines are modified
        for i in range(2, 21, 2):
            assert f'Modified Line {i:02d}' in content

        # Check that odd lines are unchanged
        for i in range(1, 21, 2):
            assert f'Line {i:02d}' in content


class TestMultiEdit(TestMultiEditBase, BaseToolTest):
    """Test cases for the MultiEdit tool."""

    __test__ = True  # Enable testing for this class


class TestMultiEditSpecial(BaseToolTest):
    """Special test cases that don't need parametrization."""

    @patch('klaudecode.tools.multi_edit.write_file_content')
    def test_multi_edit_write_failure(self, mock_write):
        """Test handling of file write failures."""
        test_file = self.create_test_file('test.txt', 'Original content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        # Simulate write failure
        mock_write.return_value = 'Permission denied'

        edits = [{'old_string': 'Original', 'new_string': 'Modified'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'Failed to write file' in result.error_msg
        # Original content should be restored
        assert test_file.read_text() == 'Original content'

    @patch('klaudecode.tools.multi_edit.create_backup')
    def test_multi_edit_backup_failure(self, mock_backup):
        """Test handling when backup creation fails."""
        test_file = self.create_test_file('test.txt', 'Original content')
        self.mock_agent.session.file_tracker.track(str(test_file))

        # Simulate backup failure
        mock_backup.side_effect = Exception('Backup failed')

        edits = [{'old_string': 'Original', 'new_string': 'Modified'}]

        result = self.invoke_tool(MultiEdit, {'file_path': str(test_file), 'edits': edits})

        assert result.tool_call.status == 'error'
        assert 'MultiEdit aborted' in result.error_msg
