from klaudecode.tools.ls import LsTool

from tests.base import BaseToolTest


class TestLsTool(BaseToolTest):
    """Test cases for the LS tool."""

    def test_list_empty_directory(self):
        """Test listing an empty directory."""
        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert result.content is not None
        assert result.extra_data.get("path_count", 0) == 0

    def test_list_directory_with_files(self):
        """Test listing a directory with files and subdirectories."""
        # Create test structure
        self.create_test_file("file1.txt", "content1")
        self.create_test_file("file2.py", "content2")
        subdir = self.temp_path / "subdir"
        subdir.mkdir()
        self.create_test_file("subdir/file3.txt", "content3")

        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "file1.txt" in result.content
        assert "file2.py" in result.content
        assert "subdir" in result.content
        assert result.extra_data.get("path_count", 0) >= 3

    def test_list_non_existent_directory(self):
        """Test listing a non-existent directory."""
        result = self.invoke_tool(LsTool, {"path": str(self.temp_path / "non_existent")})

        # LS tool returns success but with error message in content
        assert result.tool_call.status == "success"
        assert "Path does not exist" in result.content

    def test_list_file_instead_of_directory(self):
        """Test listing a file instead of a directory."""
        test_file = self.create_test_file("test.txt", "content")

        result = self.invoke_tool(LsTool, {"path": str(test_file)})

        # LS tool returns success but with error message in content
        assert result.tool_call.status == "success"
        assert "Path is not a directory" in result.content

    def test_list_with_ignore_patterns(self):
        """Test listing with ignore patterns."""
        # Create test structure
        self.create_test_file("test.py", "python file")
        self.create_test_file("test.txt", "text file")
        self.create_test_file("test.log", "log file")
        self.create_test_file(".hidden", "hidden file")

        # Ignore .log files
        result = self.invoke_tool(LsTool, {"path": str(self.temp_path), "ignore": ["*.log"]})

        assert result.tool_call.status == "success"
        assert "test.py" in result.content
        assert "test.txt" in result.content
        assert "test.log" not in result.content
        # Hidden files are not shown by default
        assert ".hidden" not in result.content

    def test_list_deeply_nested_structure(self):
        """Test listing a deeply nested directory structure."""
        # Create nested structure
        deep_path = self.temp_path / "a" / "b" / "c" / "d"
        deep_path.mkdir(parents=True)
        self.create_test_file("a/file1.txt", "content")
        self.create_test_file("a/b/file2.txt", "content")
        self.create_test_file("a/b/c/file3.txt", "content")
        self.create_test_file("a/b/c/d/file4.txt", "content")

        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "a" in result.content
        assert "b" in result.content
        assert "c" in result.content
        assert "d" in result.content
        assert result.extra_data.get("path_count", 0) >= 8  # 4 dirs + 4 files

    def test_list_with_multiple_ignore_patterns(self):
        """Test listing with multiple ignore patterns."""
        # Create test structure
        self.create_test_file("app.py", "app code")
        self.create_test_file("test_app.py", "test code")
        self.create_test_file("README.md", "readme")
        self.create_test_file("config.json", "config")
        subdir = self.temp_path / "__pycache__"
        subdir.mkdir()
        self.create_test_file("__pycache__/app.pyc", "compiled")

        # Ignore test files and __pycache__
        result = self.invoke_tool(
            LsTool,
            {"path": str(self.temp_path), "ignore": ["test_*.py", "__pycache__"]},
        )

        assert result.tool_call.status == "success"
        assert "app.py" in result.content
        assert "README.md" in result.content
        assert "test_app.py" not in result.content
        assert "__pycache__" not in result.content

    def test_list_empty_directory_with_hidden_files(self):
        """Test that hidden files are not shown by default."""
        # Create only hidden files
        self.create_test_file(".gitignore", "*.pyc")
        self.create_test_file(".env", "SECRET=value")

        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        # Hidden files should not be shown
        assert ".gitignore" not in result.content
        assert ".env" not in result.content
        assert result.extra_data.get("path_count", 0) == 0

    def test_list_mixed_content(self):
        """Test listing directory with various file types."""
        # Create mixed content (avoid file types that are ignored by default)
        self.create_test_file("script.py", "#!/usr/bin/env python")
        self.create_test_file("data.json", '{"key": "value"}')
        self.create_test_file("config.yaml", "key: value")
        self.create_test_file("readme.txt", "documentation")

        media_dir = self.temp_path / "media"
        media_dir.mkdir()
        self.create_test_file("media/style.css", "body { color: red; }")

        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"
        assert "script.py" in result.content
        assert "data.json" in result.content
        assert "config.yaml" in result.content
        assert "readme.txt" in result.content
        assert "media" in result.content

    def test_list_with_symlinks(self):
        """Test listing directory containing symlinks."""
        # Create a file and a symlink to it
        target_file = self.create_test_file("target.txt", "target content")
        link_path = self.temp_path / "link.txt"

        try:
            link_path.symlink_to(target_file)

            result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

            assert result.tool_call.status == "success"
            assert "target.txt" in result.content
            assert "link.txt" in result.content
        except OSError:
            # Skip test if symlinks are not supported (e.g., on Windows without admin rights)
            pass

    def test_list_respects_gitignore(self):
        """Test that LS tool respects .gitignore patterns from current working directory."""
        import os

        original_cwd = os.getcwd()

        try:
            # Change to the temp directory so .gitignore will be read
            os.chdir(self.temp_path)

            # Create .gitignore file
            gitignore_content = """# Test gitignore
*.pyc
__pycache__/
temp/
build/
*.tmp
secret.txt
"""
            self.create_test_file(".gitignore", gitignore_content)

            # Create files that should be ignored
            self.create_test_file("module.pyc", "compiled python")
            self.create_test_file("data.tmp", "temporary data")
            self.create_test_file("secret.txt", "secret content")

            # Create directories that should be ignored
            pycache_dir = self.temp_path / "__pycache__"
            pycache_dir.mkdir()
            self.create_test_file("__pycache__/module.cpython-39.pyc", "cached")

            temp_dir = self.temp_path / "temp"
            temp_dir.mkdir()
            self.create_test_file("temp/tempfile.txt", "temp content")

            build_dir = self.temp_path / "build"
            build_dir.mkdir()
            self.create_test_file("build/output.o", "build artifact")

            # Create files that should NOT be ignored
            self.create_test_file("main.py", "python source")
            self.create_test_file("config.json", "configuration")
            self.create_test_file("readme.txt", "documentation")

            result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

            assert result.tool_call.status == "success"

            # Check that ignored files/dirs are not in the output
            assert "module.pyc" not in result.content
            assert "data.tmp" not in result.content
            assert "secret.txt" not in result.content
            assert "__pycache__" not in result.content
            assert "temp" not in result.content
            assert "build" not in result.content

            # Check that non-ignored files are in the output
            assert "main.py" in result.content
            assert "config.json" in result.content
            assert "readme.txt" in result.content
            # .gitignore is a hidden file, so it won't be shown by default

        finally:
            os.chdir(original_cwd)

    def test_list_output_format(self):
        """Test that LS tool output follows the correct markdown list format."""
        # Create a test structure
        self.create_test_file("file1.txt", "content")
        self.create_test_file("file2.py", "content")

        # Create nested directories and files
        subdir1 = self.temp_path / "subdir1"
        subdir1.mkdir()
        self.create_test_file("subdir1/nested_file.txt", "content")

        subdir2 = self.temp_path / "subdir2"
        subdir2.mkdir()
        self.create_test_file("subdir2/another_file.py", "content")

        # Create deeper nesting
        deep_dir = subdir1 / "deep"
        deep_dir.mkdir()
        self.create_test_file("subdir1/deep/deep_file.txt", "content")

        result = self.invoke_tool(LsTool, {"path": str(self.temp_path)})

        assert result.tool_call.status == "success"

        # Check the format
        lines = result.content.strip().split("\n")

        # First line should be the root path with trailing slash
        assert lines[0].startswith("- ")
        assert lines[0].endswith("/")
        assert str(self.temp_path) in lines[0]

        # Check indentation pattern for subdirectories and files
        # Level 1 items should have 2 spaces
        level1_items = [line for line in lines if line.startswith("  - ") and not line.startswith("    - ")]
        assert len(level1_items) > 0

        # Check that directories have trailing slashes
        for line in lines:
            if "subdir1" in line and line.strip().startswith("- "):
                assert line.strip().endswith("subdir1/")
            if "subdir2" in line and line.strip().startswith("- "):
                assert line.strip().endswith("subdir2/")

        # Check that files don't have trailing slashes
        for line in lines:
            if "file1.txt" in line:
                assert not line.strip().endswith("/")
            if "file2.py" in line:
                assert not line.strip().endswith("/")

        # Check nested items have proper indentation (4 spaces for level 2)
        for line in lines:
            if "nested_file.txt" in line:
                assert line.startswith("    - ")  # 4 spaces
            if "deep/" in line and "subdir1" not in line:
                assert line.startswith("    - ")  # 4 spaces

        # Check deeper nested items (6 spaces for level 3)
        for line in lines:
            if "deep_file.txt" in line:
                assert line.startswith("      - ")  # 6 spaces
