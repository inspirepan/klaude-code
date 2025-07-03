"""Unit tests for the Glob tool."""

from pathlib import Path
from unittest.mock import patch

import pytest

from klaudecode.tools import GlobTool as Glob
from tests.base import BaseToolTest


class TestGlobBase:
    """Base test class with test cases for the Glob tool."""

    __test__ = False  # Don't collect this base class for testing

    @pytest.fixture(autouse=True)
    def setup_fd_mock(self, has_fd):
        """Setup mock for _has_fd based on parametrization."""
        with patch('klaudecode.utils.file_utils.file_glob.FileGlob._has_fd', return_value=has_fd):
            yield

    def test_glob_simple_pattern(self):
        """Test basic glob pattern matching."""
        # Create test files
        (self.temp_path / 'file1.txt').write_text('content1')
        (self.temp_path / 'file2.txt').write_text('content2')
        (self.temp_path / 'data.json').write_text('{"key": "value"}')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.txt'})

        assert result.tool_call.status == 'success'
        assert 'file1.txt' in result.content
        assert 'file2.txt' in result.content
        assert 'data.json' not in result.content

        # Verify that absolute paths are returned
        lines = result.content.strip().split('\n')
        for line in lines:
            if line.strip() and not line.startswith('('):
                # Check if the path is absolute
                assert Path(line).is_absolute(), f'Expected absolute path but got: {line}'

    def test_glob_recursive_pattern(self):
        """Test recursive glob pattern with **."""
        # Create nested directory structure
        (self.temp_path / 'src' / 'module1').mkdir(parents=True)
        (self.temp_path / 'src' / 'module2').mkdir(parents=True)
        (self.temp_path / 'tests').mkdir()

        (self.temp_path / 'src' / 'main.py').write_text('# main')
        (self.temp_path / 'src' / 'module1' / 'foo.py').write_text('# foo')
        (self.temp_path / 'src' / 'module2' / 'bar.py').write_text('# bar')
        (self.temp_path / 'tests' / 'test_main.py').write_text('# test')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '**/*.py'})

        assert result.tool_call.status == 'success'
        assert 'src/main.py' in result.content
        assert 'src/module1/foo.py' in result.content
        assert 'src/module2/bar.py' in result.content
        assert 'tests/test_main.py' in result.content

    def test_glob_specific_subdirectory(self):
        """Test glob pattern in specific subdirectory."""
        # Create directory structure
        (self.temp_path / 'src').mkdir()
        (self.temp_path / 'docs').mkdir()

        (self.temp_path / 'src' / 'app.js').write_text('// app')
        (self.temp_path / 'src' / 'utils.js').write_text('// utils')
        (self.temp_path / 'docs' / 'readme.md').write_text('# README')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': 'src/*.js'})

        assert result.tool_call.status == 'success'
        assert 'src/app.js' in result.content
        assert 'src/utils.js' in result.content
        assert 'docs/readme.md' not in result.content

    def test_glob_character_classes(self):
        """Test glob patterns with character classes."""
        # Create test files
        (self.temp_path / 'test1.txt').write_text('test1')
        (self.temp_path / 'test2.txt').write_text('test2')
        (self.temp_path / 'test3.txt').write_text('test3')
        (self.temp_path / 'testA.txt').write_text('testA')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': 'test[0-9].txt'})

        assert result.tool_call.status == 'success'
        assert 'test1.txt' in result.content
        assert 'test2.txt' in result.content
        assert 'test3.txt' in result.content
        assert 'testA.txt' not in result.content

    def test_glob_single_character_wildcard(self):
        """Test glob pattern with ? wildcard."""
        # Create test files
        (self.temp_path / 'log1.txt').write_text('log1')
        (self.temp_path / 'log2.txt').write_text('log2')
        (self.temp_path / 'log10.txt').write_text('log10')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': 'log?.txt'})

        assert result.tool_call.status == 'success'
        assert 'log1.txt' in result.content
        assert 'log2.txt' in result.content
        assert 'log10.txt' not in result.content

    def test_glob_no_matches(self):
        """Test glob pattern with no matches."""
        # Create some files
        (self.temp_path / 'data.json').write_text('{}')
        (self.temp_path / 'config.yaml').write_text('config: true')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.xml'})

        assert result.tool_call.status == 'success'
        assert 'No files found matching the pattern' in result.content

    def test_glob_invalid_pattern(self):
        """Test invalid glob pattern."""
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '[invalid'})

        # The pattern [invalid is actually valid for glob - it just won't match anything
        assert result.tool_call.status == 'success'
        assert 'No files found matching the pattern' in result.content

    def test_glob_nonexistent_directory(self):
        """Test glob in non-existent directory."""
        result = self.invoke_tool(Glob, {'path': str(self.temp_path / 'nonexistent'), 'pattern': '*.txt'})

        assert result.tool_call.status == 'error'
        assert 'does not exist' in result.error_msg

    def test_glob_result_truncation(self):
        """Test that results are truncated when exceeding limit."""
        # Create more than 100 files
        for i in range(150):
            (self.temp_path / f'file{i:03d}.txt').write_text(f'content{i}')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.txt'})

        assert result.tool_call.status == 'success'
        # Check truncation message
        assert '(Results are truncated. Consider using a more specific path or pattern.)' in result.content

        # Count actual file lines (skip message lines)
        lines = result.content.strip().split('\n')
        file_lines = []
        for line in lines:
            if line.strip() and not line.startswith('(Results are truncated') and not line.startswith('(Too many files') and 'Consider:' not in line:
                file_lines.append(line)

        assert len(file_lines) == 100

    def test_glob_hidden_files(self):
        """Test glob pattern with hidden files."""
        # Create hidden and regular files
        (self.temp_path / '.hidden.txt').write_text('hidden')
        (self.temp_path / 'visible.txt').write_text('visible')
        (self.temp_path / '.config').mkdir()
        (self.temp_path / '.config' / 'settings.json').write_text('{}')

        # Test that * doesn't match hidden files
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.txt'})

        assert result.tool_call.status == 'success'
        assert 'visible.txt' in result.content
        assert '.hidden.txt' not in result.content

        # Test explicit pattern for hidden files - note that fd excludes hidden files by default
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '.*'})

        assert result.tool_call.status == 'success'
        # Both fd and python glob should exclude hidden files based on the implementation
        assert '.hidden.txt' not in result.content

    def test_glob_complex_pattern(self):
        """Test complex glob pattern combining multiple features."""
        # Create complex directory structure
        (self.temp_path / 'src' / 'components').mkdir(parents=True)
        (self.temp_path / 'src' / 'utils').mkdir(parents=True)
        (self.temp_path / 'tests' / 'unit').mkdir(parents=True)

        # Create various files
        (self.temp_path / 'src' / 'components' / 'Button.tsx').write_text('// Button')
        (self.temp_path / 'src' / 'components' / 'Modal.tsx').write_text('// Modal')
        (self.temp_path / 'src' / 'components' / 'Button.test.tsx').write_text('// Test')
        (self.temp_path / 'src' / 'utils' / 'helpers.ts').write_text('// helpers')
        (self.temp_path / 'tests' / 'unit' / 'Button.test.tsx').write_text('// Test')

        # Test pattern that finds all TypeScript files in src
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': 'src/**/*.ts'})

        assert result.tool_call.status == 'success'
        # Should match .ts files
        assert 'src/utils/helpers.ts' in result.content
        # Should not match .tsx files with this pattern
        assert 'src/components/Button.tsx' not in result.content

        # Test pattern for both .ts and .tsx files
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': 'src/**/*.tsx'})

        assert result.tool_call.status == 'success'
        assert 'src/components/Button.tsx' in result.content
        assert 'src/components/Modal.tsx' in result.content
        assert 'src/components/Button.test.tsx' in result.content
        assert 'tests/unit/Button.test.tsx' not in result.content

    def test_glob_gitignore_not_respected(self):
        """Test that glob does not respect .gitignore files."""
        # Create .gitignore file
        gitignore_content = """
# Ignore build directory
build/
*.pyc
temp*.txt
"""
        (self.temp_path / '.gitignore').write_text(gitignore_content.strip())

        # Create files that would be ignored by .gitignore
        (self.temp_path / 'build').mkdir()
        (self.temp_path / 'build' / 'output.txt').write_text('build output')
        (self.temp_path / 'main.pyc').write_text('compiled')
        (self.temp_path / 'temp1.txt').write_text('temp file 1')
        (self.temp_path / 'temp2.txt').write_text('temp file 2')
        (self.temp_path / 'regular.txt').write_text('regular file')

        # Test that all txt files are found, including those in .gitignore
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '**/*.txt'})

        assert result.tool_call.status == 'success'
        # Files that should be ignored by .gitignore but still found by glob
        assert 'build/output.txt' in result.content
        assert 'temp1.txt' in result.content
        assert 'temp2.txt' in result.content
        # Regular file should also be found
        assert 'regular.txt' in result.content

        # Test .pyc files are also found despite being in .gitignore
        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.pyc'})

        assert result.tool_call.status == 'success'
        assert 'main.pyc' in result.content

    def test_glob_absolute_pattern(self):
        """Test glob with absolute path pattern."""
        # Create test file
        test_file = self.temp_path / 'absolute_test.txt'
        test_file.write_text('absolute content')

        # Use absolute pattern
        result = self.invoke_tool(Glob, {'pattern': str(test_file)})

        assert result.tool_call.status == 'success'
        assert str(test_file) in result.content


@pytest.mark.parametrize('has_fd', [True, False], ids=['with_fd', 'without_fd'])
class TestGlob(TestGlobBase, BaseToolTest):
    """Test cases for the Glob tool with has_fd parametrization."""

    __test__ = True  # Enable testing for this class


class TestGlobSpecial(BaseToolTest):
    """Special test cases that don't need parametrization."""

    @patch('klaudecode.utils.file_utils.file_glob.FileGlob._execute_command')
    def test_glob_fd_fallback_to_python(self, mock_execute):
        """Test that glob falls back to Python glob when fd command fails."""
        # Simulate fd command failure
        mock_execute.return_value = ('', 'fd error', 1)

        # Create test files
        (self.temp_path / 'file1.py').write_text('# file1')
        (self.temp_path / 'file2.py').write_text('# file2')

        result = self.invoke_tool(Glob, {'path': str(self.temp_path), 'pattern': '*.py'})

        assert result.tool_call.status == 'success'
        assert 'file1.py' in result.content
        assert 'file2.py' in result.content
