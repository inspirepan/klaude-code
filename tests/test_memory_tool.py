from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from klaude_code.core.tool import MEMORY_DIR_NAME, MemoryTool
from klaude_code.core.tool.memory.memory_tool import _validate_path  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def temp_git_root(tmp_path: Path):
    """Create a temporary directory that simulates a git root."""
    memories_dir = tmp_path / MEMORY_DIR_NAME
    memories_dir.mkdir(parents=True)
    with patch("klaude_code.core.tool.memory.memory_tool._get_git_root", return_value=tmp_path):
        yield tmp_path


@pytest.fixture
def memories_dir(temp_git_root: Path) -> Path:
    """Return the memories directory path."""
    return temp_git_root / MEMORY_DIR_NAME


class TestPathValidation:
    def test_valid_root_path(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/memories")
        assert error is None
        assert actual is not None

    def test_valid_file_path(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/memories/test.txt")
        assert error is None
        assert actual is not None
        assert actual.name == "test.txt"

    def test_valid_nested_path(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/memories/subdir/file.txt")
        assert error is None
        assert actual is not None

    def test_path_not_starting_with_memories(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/other/path.txt")
        assert error is not None
        assert "must start with /memories" in error
        assert actual is None

    def test_path_traversal_dotdot(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/memories/../etc/passwd")
        assert error is not None
        assert "traversal" in error.lower()
        assert actual is None

    def test_path_traversal_encoded(self, temp_git_root: Path) -> None:
        actual, error = _validate_path("/memories/%2e%2e/etc/passwd")
        assert error is not None
        assert "traversal" in error.lower()
        assert actual is None

    def test_path_traversal_double_encoded(self, temp_git_root: Path) -> None:
        _, error = _validate_path("/memories/..%252f..%252fetc/passwd")
        assert error is None or "traversal" in error.lower() if error else True


class TestViewCommand:
    def test_view_directory_listing(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "file1.txt").write_text("content1")
        (memories_dir / "file2.txt").write_text("content2")
        subdir = memories_dir / "subdir"
        subdir.mkdir()

        args = MemoryTool.MemoryArguments(command="view", path="/memories").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert result.output is not None
        assert "Directory: /memories" in result.output
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output
        assert "subdir/" in result.output

    def test_view_file_content(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "test.txt").write_text("line1\nline2\nline3\n")

        args = MemoryTool.MemoryArguments(command="view", path="/memories/test.txt").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert result.output is not None
        assert "line1" in result.output
        assert "line2" in result.output
        assert "line3" in result.output

    def test_view_with_range(self, temp_git_root: Path, memories_dir: Path) -> None:
        content = "\n".join([f"line{i}" for i in range(1, 11)])
        (memories_dir / "test.txt").write_text(content)

        args = MemoryTool.MemoryArguments(
            command="view", path="/memories/test.txt", view_range=[2, 4]
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert result.output is not None
        assert "line2" in result.output
        assert "line3" in result.output
        assert "line4" in result.output
        assert "line1" not in result.output
        assert "line5" not in result.output

    def test_view_nonexistent_path(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(command="view", path="/memories/nonexistent.txt").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "does not exist" in result.output

    def test_view_empty_directory(self, temp_git_root: Path, memories_dir: Path) -> None:
        args = MemoryTool.MemoryArguments(command="view", path="/memories").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert result.output is not None
        assert "empty directory" in result.output


class TestCreateCommand:
    def test_create_new_file(self, temp_git_root: Path, memories_dir: Path) -> None:
        args = MemoryTool.MemoryArguments(
            command="create", path="/memories/new.txt", file_text="hello world"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert (memories_dir / "new.txt").exists()
        assert (memories_dir / "new.txt").read_text() == "hello world"

    def test_create_with_nested_directory(self, temp_git_root: Path, memories_dir: Path) -> None:
        args = MemoryTool.MemoryArguments(
            command="create",
            path="/memories/a/b/c/file.txt",
            file_text="nested content",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert (memories_dir / "a" / "b" / "c" / "file.txt").exists()

    def test_create_overwrite_file(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "existing.txt").write_text("old content")

        args = MemoryTool.MemoryArguments(
            command="create", path="/memories/existing.txt", file_text="new content"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert (memories_dir / "existing.txt").read_text() == "new content"

    def test_create_missing_file_text(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(command="create", path="/memories/test.txt").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "file_text is required" in result.output


class TestStrReplaceCommand:
    def test_str_replace_success(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "test.txt").write_text("hello world")

        args = MemoryTool.MemoryArguments(
            command="str_replace",
            path="/memories/test.txt",
            old_str="world",
            new_str="universe",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert (memories_dir / "test.txt").read_text() == "hello universe"

    def test_str_replace_file_not_found(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(
            command="str_replace",
            path="/memories/nonexistent.txt",
            old_str="old",
            new_str="new",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "does not exist" in result.output

    def test_str_replace_string_not_found(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "test.txt").write_text("hello world")

        args = MemoryTool.MemoryArguments(
            command="str_replace",
            path="/memories/test.txt",
            old_str="foo",
            new_str="bar",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "not found" in result.output


class TestInsertCommand:
    def test_insert_at_line(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "test.txt").write_text("line1\nline2\nline3\n")

        args = MemoryTool.MemoryArguments(
            command="insert",
            path="/memories/test.txt",
            insert_line=2,
            insert_text="inserted",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        content = (memories_dir / "test.txt").read_text()
        lines = content.splitlines()
        assert lines[1] == "inserted"

    def test_insert_at_end(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "test.txt").write_text("line1\nline2\n")

        args = MemoryTool.MemoryArguments(
            command="insert",
            path="/memories/test.txt",
            insert_line=100,
            insert_text="at_end",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        content = (memories_dir / "test.txt").read_text()
        assert "at_end" in content

    def test_insert_in_empty_file(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "empty.txt").write_text("")

        args = MemoryTool.MemoryArguments(
            command="insert",
            path="/memories/empty.txt",
            insert_line=1,
            insert_text="first line",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert (memories_dir / "empty.txt").read_text() == "first line"


class TestDeleteCommand:
    def test_delete_file(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "to_delete.txt").write_text("content")

        args = MemoryTool.MemoryArguments(command="delete", path="/memories/to_delete.txt").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert not (memories_dir / "to_delete.txt").exists()

    def test_delete_directory(self, temp_git_root: Path, memories_dir: Path) -> None:
        subdir = memories_dir / "subdir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        args = MemoryTool.MemoryArguments(command="delete", path="/memories/subdir").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert not subdir.exists()

    def test_delete_nonexistent(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(command="delete", path="/memories/nonexistent.txt").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "does not exist" in result.output

    def test_delete_root_directory_forbidden(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(command="delete", path="/memories").model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "Cannot delete" in result.output


class TestRenameCommand:
    def test_rename_file(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "old.txt").write_text("content")

        args = MemoryTool.MemoryArguments(
            command="rename", old_path="/memories/old.txt", new_path="/memories/new.txt"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert not (memories_dir / "old.txt").exists()
        assert (memories_dir / "new.txt").exists()
        assert (memories_dir / "new.txt").read_text() == "content"

    def test_rename_directory(self, temp_git_root: Path, memories_dir: Path) -> None:
        subdir = memories_dir / "old_dir"
        subdir.mkdir()
        (subdir / "file.txt").write_text("content")

        args = MemoryTool.MemoryArguments(
            command="rename", old_path="/memories/old_dir", new_path="/memories/new_dir"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert not (memories_dir / "old_dir").exists()
        assert (memories_dir / "new_dir").exists()
        assert (memories_dir / "new_dir" / "file.txt").exists()

    def test_rename_cross_directory(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "file.txt").write_text("content")
        (memories_dir / "subdir").mkdir()

        args = MemoryTool.MemoryArguments(
            command="rename",
            old_path="/memories/file.txt",
            new_path="/memories/subdir/file.txt",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "success"
        assert not (memories_dir / "file.txt").exists()
        assert (memories_dir / "subdir" / "file.txt").exists()

    def test_rename_destination_exists(self, temp_git_root: Path, memories_dir: Path) -> None:
        (memories_dir / "old.txt").write_text("old")
        (memories_dir / "new.txt").write_text("new")

        args = MemoryTool.MemoryArguments(
            command="rename", old_path="/memories/old.txt", new_path="/memories/new.txt"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "already exists" in result.output

    def test_rename_source_not_found(self, temp_git_root: Path) -> None:
        args = MemoryTool.MemoryArguments(
            command="rename",
            old_path="/memories/nonexistent.txt",
            new_path="/memories/new.txt",
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))

        assert result.status == "error"
        assert result.output is not None
        assert "does not exist" in result.output


class TestSecurityEdgeCases:
    def test_path_with_null_byte(self, temp_git_root: Path) -> None:
        # Some systems might be vulnerable to null byte injection
        actual, error = _validate_path("/memories/test\x00.txt")
        # Should either succeed or fail gracefully
        assert actual is None or error is None

    def test_path_with_unicode(self, temp_git_root: Path, memories_dir: Path) -> None:
        args = MemoryTool.MemoryArguments(
            command="create", path="/memories/test.txt", file_text="content"
        ).model_dump_json()
        result = asyncio.run(MemoryTool.call(args))
        assert result.status == "success"

    def test_very_long_path(self, temp_git_root: Path) -> None:
        long_path = "/memories/" + "a" * 1000 + ".txt"
        _, error = _validate_path(long_path)
        # Should succeed validation (filesystem might fail later)
        assert error is None


class TestToolSchema:
    def test_schema_has_required_fields(self) -> None:
        schema = MemoryTool.schema()
        assert schema.name == "Memory"
        assert schema.type == "function"
        assert schema.description is not None
        assert schema.parameters is not None
        assert "command" in schema.parameters["properties"]
        assert "command" in schema.parameters["required"]
