"""Unit tests for the Grep tool."""

from unittest.mock import patch

import pytest
from klaudecode.tools import GrepTool as Grep

from tests.base import BaseToolTest


class TestGrepBase:
    """Base test class with test cases for the Grep tool."""

    __test__ = False  # Don't collect this base class for testing

    @pytest.fixture(autouse=True)
    def setup_rg_mock(self, has_rg):
        """Setup mock for _has_ripgrep based on parametrization."""
        with patch("klaudecode.tools.grep.GrepTool._has_ripgrep", return_value=has_rg):
            yield

    def test_grep_simple_pattern(self):
        """Test basic grep pattern matching."""
        # Create test files
        (self.temp_path / "file1.txt").write_text("hello world\nthis is a test\nhello again")
        (self.temp_path / "file2.txt").write_text("goodbye world\nanother test")
        (self.temp_path / "file3.py").write_text('def hello():\n    print("hello")')

        result = self.invoke_tool(Grep, {"pattern": "hello", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "file1.txt:1" in result.content
        assert "file1.txt:3" in result.content
        assert "file3.py:1" in result.content
        assert "file3.py:2" in result.content
        assert "file2.txt" not in result.content

    def test_grep_regex_pattern(self, has_rg):
        """Test grep with regex patterns."""
        # Create test files
        (self.temp_path / "test.txt").write_text("test1\nnothing\ntest2\ntest123\ntest")

        if has_rg:
            # ripgrep supports \d+ pattern
            result = self.invoke_tool(Grep, {"pattern": r"test\d+", "path": str(self.temp_path)})
            assert result.tool_call.status == "success"
            assert "test.txt:1" in result.content  # test1
            assert "test.txt:3" in result.content  # test2
            assert "test.txt:4" in result.content  # test123
            assert "test.txt:5" not in result.content  # plain 'test'
        else:
            # standard grep needs simpler pattern - matches single digit
            result = self.invoke_tool(Grep, {"pattern": r"test[0-9]", "path": str(self.temp_path)})
            assert result.tool_call.status == "success"
            assert "test.txt:1" in result.content  # test1
            assert "test.txt:3" in result.content  # test2
            assert "test.txt:4" in result.content  # test123 (matches first digit)

    def test_grep_with_include_pattern(self):
        """Test grep with file include pattern."""
        # Create test files
        (self.temp_path / "file1.py").write_text("import os\nimport sys")
        (self.temp_path / "file2.txt").write_text("import nothing\nimport everything")
        (self.temp_path / "file3.js").write_text('import React from "react"')

        result = self.invoke_tool(Grep, {"pattern": "import", "path": str(self.temp_path), "include": "*.py"})

        assert result.tool_call.status == "success"
        assert "file1.py:1" in result.content
        assert "file1.py:2" in result.content
        assert "file2.txt" not in result.content
        assert "file3.js" not in result.content

    def test_grep_word_boundaries(self):
        """Test grep with word boundary patterns."""
        # Create test file
        (self.temp_path / "code.txt").write_text("test\ntesting\ncontest\ntest123")

        result = self.invoke_tool(Grep, {"pattern": r"\btest\b", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "code.txt:1" in result.content  # 'test' alone
        assert "code.txt:2" not in result.content  # 'testing'
        assert "code.txt:3" not in result.content  # 'contest'

    def test_grep_case_sensitive(self):
        """Test that grep is case sensitive."""
        # Create test file
        (self.temp_path / "case.txt").write_text("Hello\nhello\nHELLO")

        result = self.invoke_tool(Grep, {"pattern": "hello", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "case.txt:2" in result.content
        assert "case.txt:1" not in result.content
        assert "case.txt:3" not in result.content

    def test_grep_no_matches(self):
        """Test grep with no matching pattern."""
        # Create test files
        (self.temp_path / "file1.txt").write_text("hello world")
        (self.temp_path / "file2.txt").write_text("goodbye world")

        result = self.invoke_tool(Grep, {"pattern": "nonexistent", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "No matches found" in result.content

    def test_grep_invalid_regex(self):
        """Test grep with invalid regex pattern."""
        result = self.invoke_tool(Grep, {"pattern": "[invalid(", "path": str(self.temp_path)})

        assert result.tool_call.status == "error"
        assert "Invalid regex pattern" in result.error_msg

    def test_grep_nonexistent_path(self):
        """Test grep with non-existent path."""
        result = self.invoke_tool(Grep, {"pattern": "test", "path": str(self.temp_path / "nonexistent")})

        assert result.tool_call.status == "error"
        assert "does not exist" in result.error_msg

    def test_grep_nested_directories(self):
        """Test grep searches recursively in nested directories."""
        # Create nested directory structure
        (self.temp_path / "src" / "module").mkdir(parents=True)
        (self.temp_path / "tests").mkdir()

        (self.temp_path / "file1.txt").write_text("pattern here")
        (self.temp_path / "src" / "file2.txt").write_text("pattern in src")
        (self.temp_path / "src" / "module" / "file3.txt").write_text("pattern in module")
        (self.temp_path / "tests" / "test.txt").write_text("pattern in tests")

        result = self.invoke_tool(Grep, {"pattern": "pattern", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "file1.txt:1" in result.content
        assert "src/file2.txt:1" in result.content
        assert "src/module/file3.txt:1" in result.content
        assert "tests/test.txt:1" in result.content

    def test_grep_multiline_matches(self):
        """Test grep with patterns across multiple lines."""
        # Create test file with multiple matches
        content = """Line 1: TODO fix this
Line 2: no match here
Line 3: TODO implement feature
Line 4: regular line
Line 5: TODO review code"""
        (self.temp_path / "tasks.txt").write_text(content)

        result = self.invoke_tool(Grep, {"pattern": "TODO", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "tasks.txt:1" in result.content
        assert "tasks.txt:3" in result.content
        assert "tasks.txt:5" in result.content
        assert "tasks.txt:2" not in result.content
        assert "tasks.txt:4" not in result.content

    def test_grep_special_characters(self):
        """Test grep with special regex characters."""
        # Create test file
        (self.temp_path / "special.txt").write_text("test.py\ntest?py\ntest*py\ntest+py")

        # Search for literal dot
        result = self.invoke_tool(Grep, {"pattern": r"test\.py", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "special.txt:1" in result.content
        assert "special.txt:2" not in result.content

    def test_grep_line_numbers(self):
        """Test that grep returns correct line numbers."""
        # Create test file with specific content
        content = """First line
Second line with match
Third line
Fourth line with match
Fifth line"""
        (self.temp_path / "numbered.txt").write_text(content)

        result = self.invoke_tool(Grep, {"pattern": "with match", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "numbered.txt:2" in result.content
        assert "numbered.txt:4" in result.content

    def test_grep_include_multiple_extensions(self, has_rg):
        """Test grep with multiple file extensions in include pattern."""
        # Create test files
        (self.temp_path / "file1.py").write_text("import os")
        (self.temp_path / "file2.js").write_text("import React")
        (self.temp_path / "file3.txt").write_text("import nothing")
        (self.temp_path / "file4.md").write_text("import statement")

        if has_rg:
            # ripgrep supports brace expansion in glob patterns
            result = self.invoke_tool(
                Grep,
                {
                    "pattern": "import",
                    "path": str(self.temp_path),
                    "include": "*.{py,js}",
                },
            )
            assert result.tool_call.status == "success"
            assert "file1.py:1" in result.content
            assert "file2.js:1" in result.content
            assert "file3.txt" not in result.content
            assert "file4.md" not in result.content
        else:
            # standard grep doesn't support brace expansion, test single extension
            result = self.invoke_tool(
                Grep,
                {"pattern": "import", "path": str(self.temp_path), "include": "*.py"},
            )
            assert result.tool_call.status == "success"
            assert "file1.py:1" in result.content
            assert "file2.js" not in result.content

    def test_grep_ignores_gitignore_patterns(self, has_rg):
        """Test that grep ignores files matching gitignore patterns."""
        # Create files that would typically be ignored
        (self.temp_path / "node_modules").mkdir()
        (self.temp_path / ".git").mkdir()
        (self.temp_path / "__pycache__").mkdir()

        (self.temp_path / "main.py").write_text("pattern here")
        (self.temp_path / "node_modules" / "lib.js").write_text("pattern in node_modules")
        (self.temp_path / ".git" / "config").write_text("pattern in git")
        (self.temp_path / "__pycache__" / "cache.pyc").write_text("pattern in pycache")

        result = self.invoke_tool(Grep, {"pattern": "pattern", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "main.py:1" in result.content

        if has_rg:
            # ripgrep respects the ignore patterns
            assert "node_modules" not in result.content
            assert ".git" not in result.content
            assert "__pycache__" not in result.content
        else:
            # standard grep doesn't respect ignore patterns by default
            # It will find all matches
            pass

    def test_grep_empty_files(self):
        """Test grep with empty files."""
        # Create empty file and file with content
        (self.temp_path / "empty.txt").write_text("")
        (self.temp_path / "content.txt").write_text("has content")

        result = self.invoke_tool(Grep, {"pattern": "content", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "content.txt:1" in result.content
        assert "empty.txt" not in result.content

    def test_grep_binary_files_skipped(self):
        """Test that grep skips binary files."""
        # Create a binary file and a text file
        (self.temp_path / "binary.bin").write_bytes(b"\x00\x01\x02\x03pattern\x04\x05")
        (self.temp_path / "text.txt").write_text("pattern in text")

        result = self.invoke_tool(Grep, {"pattern": "pattern", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "text.txt:1" in result.content
        # Binary file should be skipped
        assert "binary.bin" not in result.content


@pytest.mark.parametrize("has_rg", [True, False], ids=["with_ripgrep", "without_ripgrep"])
class TestGrep(TestGrepBase, BaseToolTest):
    """Test cases for the Grep tool with has_rg parametrization."""

    __test__ = True  # Enable testing for this class


class TestGrepSpecial(BaseToolTest):
    """Special test cases that don't need parametrization."""

    def test_grep_result_truncation(self):
        """Test that results are truncated when exceeding limit."""
        # Create many files with matches
        for i in range(150):
            (self.temp_path / f"file{i:03d}.txt").write_text("match on line 1\nmatch on line 2")

        result = self.invoke_tool(Grep, {"pattern": "match", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "showing first 100 of" in result.content
        assert "Too many results" in result.content

    def test_grep_max_matches_per_file(self):
        """Test that matches per file are limited."""
        # Create file with many matches (more than DEFAULT_MAX_MATCHES_PER_FILE=10)
        lines = [f"match {i}" for i in range(20)]
        (self.temp_path / "many_matches.txt").write_text("\n".join(lines))

        result = self.invoke_tool(Grep, {"pattern": "match", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        # Count how many line numbers are reported for this file
        matches = [line for line in result.content.split("\n") if "many_matches.txt:" in line]
        assert len(matches) <= 10  # Should be limited to DEFAULT_MAX_MATCHES_PER_FILE

    @patch("klaudecode.tools.grep.GrepTool._execute_search_command")
    def test_grep_timeout_handling(self, mock_execute):
        """Test handling of search timeout."""
        # Simulate timeout
        mock_execute.return_value = ("", "Search timed out after 30 seconds", 1)

        result = self.invoke_tool(Grep, {"pattern": "test", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "Error: Search timed out" in result.content

    @patch("klaudecode.tools.grep.GrepTool._execute_search_command")
    def test_grep_command_failure(self, mock_execute):
        """Test handling of command execution failure."""
        # Simulate command failure
        mock_execute.return_value = ("", "Command execution failed: some error", 1)

        result = self.invoke_tool(Grep, {"pattern": "test", "path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "Search completed with warnings" in result.content
