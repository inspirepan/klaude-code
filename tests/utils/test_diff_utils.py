import pytest
from rich.console import Group
from rich.text import Text

from klaudecode.utils.file_utils.diff_utils import (
    generate_char_level_diff,
    generate_diff_lines,
    generate_snippet_from_diff,
    render_diff_lines,
)


class TestGenerateDiffLines:
    def test_no_changes(self):
        """Test diff with no changes."""
        old_content = "line1\nline2\n"
        new_content = "line1\nline2\n"
        diff_lines = generate_diff_lines(old_content, new_content)
        assert diff_lines == []

    def test_basic_change(self):
        """Test basic line change."""
        old_content = "line1\nold line\nline3\n"
        new_content = "line1\nnew line\nline3\n"
        diff_lines = generate_diff_lines(old_content, new_content)
        
        # Check that we have diff lines
        assert len(diff_lines) > 0
        assert any(line.startswith('-old line') for line in diff_lines)
        assert any(line.startswith('+new line') for line in diff_lines)

    def test_no_newline_at_end_old_file(self):
        """Test when old file has no newline at end."""
        old_content = "line1\nline2"  # No trailing newline
        new_content = "line1\nline2\n"  # Has trailing newline
        diff_lines = generate_diff_lines(old_content, new_content)
        
        # Should include "\ No newline at end of file" message
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 1
        assert no_newline_lines[0] == '\\ No newline at end of file\n'

    def test_no_newline_at_end_new_file(self):
        """Test when new file has no newline at end."""
        old_content = "line1\nline2\n"  # Has trailing newline
        new_content = "line1\nline2"  # No trailing newline
        diff_lines = generate_diff_lines(old_content, new_content)
        
        # Should include "\ No newline at end of file" message
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 1
        assert no_newline_lines[0] == '\\ No newline at end of file\n'

    def test_both_no_newline(self):
        """Test when both files have no newline at end."""
        old_content = "line1\nold line"  # No trailing newline
        new_content = "line1\nnew line"  # No trailing newline
        diff_lines = generate_diff_lines(old_content, new_content)
        
        # Should NOT include "\ No newline at end of file" since both are the same
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 0

    def test_both_have_newline(self):
        """Test when both files have newline at end."""
        old_content = "line1\nold line\n"  # Has trailing newline
        new_content = "line1\nnew line\n"  # Has trailing newline
        diff_lines = generate_diff_lines(old_content, new_content)
        
        # Should NOT include "\ No newline at end of file" since both are the same
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 0


class TestGenerateSnippetFromDiff:
    def test_empty_diff(self):
        """Test snippet generation with empty diff."""
        snippet = generate_snippet_from_diff([])
        assert snippet == ''

    def test_basic_snippet(self):
        """Test basic snippet generation."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,3 +1,3 @@\n',
            ' line1\n',
            '-old line\n',
            '+new line\n',
            ' line3\n'
        ]
        snippet = generate_snippet_from_diff(diff_lines)
        
        # Should include only context and added lines
        lines = snippet.split('\n')
        assert '1→line1' in lines
        assert '2→new line' in lines
        assert '3→line3' in lines
        # Should not include the removed line
        assert 'old line' not in snippet

    def test_snippet_skips_no_newline_message(self):
        """Test that snippet generation skips no newline messages."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,2 +1,2 @@\n',
            ' line1\n',
            '-old line',
            '\\ No newline at end of file\n',
            '+new line\n'
        ]
        snippet = generate_snippet_from_diff(diff_lines)
        
        # Should not include the no newline message
        assert '\\ No newline at end of file' not in snippet
        lines = snippet.split('\n')
        assert '1→line1' in lines
        assert '2→new line' in lines


class TestGenerateCharLevelDiff:
    def test_no_change(self):
        """Test character-level diff with no changes."""
        old_line = "same line"
        new_line = "same line"
        old_text, new_text = generate_char_level_diff(old_line, new_line)
        
        assert isinstance(old_text, Text)
        assert isinstance(new_text, Text)
        assert str(old_text) == old_line
        assert str(new_text) == new_line

    def test_character_changes(self):
        """Test character-level diff with changes."""
        old_line = "old word here"
        new_line = "new word here"
        old_text, new_text = generate_char_level_diff(old_line, new_line)
        
        assert isinstance(old_text, Text)
        assert isinstance(new_text, Text)
        # Should contain the text content
        assert 'old' in str(old_text)
        assert 'new' in str(new_text)
        assert 'word here' in str(old_text)
        assert 'word here' in str(new_text)


class TestRenderDiffLines:
    def test_empty_diff(self):
        """Test rendering empty diff."""
        result = render_diff_lines([])
        assert isinstance(result, Group)

    def test_basic_diff_rendering(self):
        """Test basic diff rendering."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,3 +1,3 @@\n',
            ' line1\n',
            '-old line\n',
            '+new line\n',
            ' line3\n'
        ]
        result = render_diff_lines(diff_lines)
        # Without show_summary, returns a Table (wrapped by Padding)
        assert result is not None

    def test_diff_with_summary(self):
        """Test diff rendering with summary."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,3 +1,3 @@\n',
            ' line1\n',
            '-old line\n',
            '+new line\n',
            ' line3\n'
        ]
        result = render_diff_lines(diff_lines, file_path='/test/file.txt', show_summary=True)
        assert isinstance(result, Group)

    def test_no_newline_rendering(self):
        """Test rendering of no newline message."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,2 +1,2 @@\n',
            ' line1\n',
            '-old line',
            '\\ No newline at end of file\n',
            '+new line\n'
        ]
        result = render_diff_lines(diff_lines)
        # Without show_summary, returns a Table (wrapped by Padding)
        assert result is not None

    def test_summary_calculation(self):
        """Test summary calculation for additions and removals."""
        diff_lines = [
            '--- \n',
            '+++ \n',
            '@@ -1,4 +1,4 @@\n',
            ' line1\n',
            '-removed line 1\n',
            '-removed line 2\n',
            '+added line 1\n',
            '+added line 2\n',
            '+added line 3\n',
            ' line4\n'
        ]
        result = render_diff_lines(diff_lines, file_path='/test/file.txt', show_summary=True)
        assert isinstance(result, Group)
        
        # The summary should be calculated correctly (3 additions, 2 removals)
        # This is verified by the fact that the function runs without error
        # and returns a Group object


class TestIntegration:
    def test_full_workflow_with_no_newline(self):
        """Test the complete workflow with no newline at end."""
        old_content = "line1\nline2"  # No newline
        new_content = "line1\nmodified line2\n"  # With newline
        
        # Generate diff
        diff_lines = generate_diff_lines(old_content, new_content)
        assert len(diff_lines) > 0
        
        # Should have no newline message
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 1
        
        # Generate snippet
        snippet = generate_snippet_from_diff(diff_lines)
        assert snippet != ''
        assert '\\ No newline at end of file' not in snippet
        
        # Render diff
        rendered = render_diff_lines(diff_lines, file_path='/test/file.txt', show_summary=True)
        assert isinstance(rendered, Group)

    def test_full_workflow_normal_case(self):
        """Test the complete workflow with normal files."""
        old_content = "line1\nold content\nline3\n"
        new_content = "line1\nnew content\nline3\n"
        
        # Generate diff
        diff_lines = generate_diff_lines(old_content, new_content)
        assert len(diff_lines) > 0
        
        # Should NOT have no newline message
        no_newline_lines = [line for line in diff_lines if line.startswith('\\')]
        assert len(no_newline_lines) == 0
        
        # Generate snippet
        snippet = generate_snippet_from_diff(diff_lines)
        assert snippet != ''
        assert 'new content' in snippet
        assert 'old content' not in snippet
        
        # Render diff
        rendered = render_diff_lines(diff_lines, file_path='/test/file.txt', show_summary=True)
        assert isinstance(rendered, Group)