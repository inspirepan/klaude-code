"""Tests for Move tool."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from klaude_code.core.tool import (
    MoveTool,
    ReadTool,
    ToolContextToken,
    reset_tool_context,
    set_tool_context_from_session,
)
from klaude_code.session.session import Session


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.session = Session(work_dir=Path.cwd())
        self._token: ToolContextToken = set_tool_context_from_session(self.session)

    def tearDown(self) -> None:
        reset_tool_context(self._token)
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


class TestMoveTool(BaseTempDirTest):
    def test_move_basic(self) -> None:
        """Basic move from one file to a new file."""
        source = os.path.abspath("source.py")
        target = os.path.abspath("target.py")

        with open(source, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")

        # Read source first
        arun(ReadTool.call(json.dumps({"file_path": source})))

        # Cut lines 2-4 and paste into new file
        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 2,
                        "end_line": 4,
                        "target_file_path": target,
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "success")
        self.assertIn("Moved 3 lines", res.output)
        self.assertIn("Source file context (after move):", res.output)
        self.assertIn("Target file context (after insert):", res.output)
        self.assertIn("-------- cut here --------", res.output)
        self.assertIn("-------- inserted --------", res.output)
        self.assertIn("line2", res.output)
        self.assertIn("line3", res.output)
        self.assertIn("line4", res.output)

        # Verify source file
        with open(source, encoding="utf-8") as f:
            source_content = f.read()
        self.assertEqual(source_content, "line1\nline5\n")

        # Verify target file
        with open(target, encoding="utf-8") as f:
            target_content = f.read()
        self.assertEqual(target_content, "line2\nline3\nline4\n")

    def test_move_into_existing_file(self) -> None:
        """Move into an existing file at specific line."""
        source = os.path.abspath("source.txt")
        target = os.path.abspath("target.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("A\nB\nC\n")
        with open(target, "w", encoding="utf-8") as f:
            f.write("X\nY\nZ\n")

        # Read both files
        arun(ReadTool.call(json.dumps({"file_path": source})))
        arun(ReadTool.call(json.dumps({"file_path": target})))

        # Cut line 2 (B) from source and insert at line 2 in target
        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 2,
                        "end_line": 2,
                        "target_file_path": target,
                        "insert_line": 2,
                    }
                )
            )
        )

        self.assertEqual(res.status, "success")

        with open(source, encoding="utf-8") as f:
            self.assertEqual(f.read(), "A\nC\n")

        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "X\nB\nY\nZ\n")

    def test_move_same_file_down(self) -> None:
        """Move lines within the same file (down)."""
        file_path = os.path.abspath("same.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("1\n2\n3\n4\n5\n")

        arun(ReadTool.call(json.dumps({"file_path": file_path})))

        # Move lines 1-2 to after line 4 (insert at line 5)
        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": file_path,
                        "start_line": 1,
                        "end_line": 2,
                        "target_file_path": file_path,
                        "insert_line": 5,
                    }
                )
            )
        )

        self.assertEqual(res.status, "success")
        self.assertIn("Moved 2 lines within", res.output)
        self.assertIn("Source context (after cut):", res.output)
        self.assertIn("Insert context:", res.output)
        self.assertIn("-------- cut here --------", res.output)
        self.assertIn("-------- inserted --------", res.output)

        with open(file_path, encoding="utf-8") as f:
            # After removing 1,2 we have 3,4,5; then insert 1,2 at position 3 (was 5)
            self.assertEqual(f.read(), "3\n4\n1\n2\n5\n")

    def test_move_same_file_up(self) -> None:
        """Move lines within the same file (up)."""
        file_path = os.path.abspath("same2.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("1\n2\n3\n4\n5\n")

        arun(ReadTool.call(json.dumps({"file_path": file_path})))

        # Move lines 4-5 to line 1 (beginning)
        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": file_path,
                        "start_line": 4,
                        "end_line": 5,
                        "target_file_path": file_path,
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "success")

        with open(file_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "4\n5\n1\n2\n3\n")

    def test_move_requires_read_source(self) -> None:
        """Source file must be read first."""
        source = os.path.abspath("unread_source.txt")
        target = os.path.abspath("target2.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("hello\n")

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 1,
                        "end_line": 1,
                        "target_file_path": target,
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("Source file has not been read yet", res.output)

    def test_move_requires_read_target(self) -> None:
        """Existing target file must be read first."""
        source = os.path.abspath("source3.txt")
        target = os.path.abspath("unread_target.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("hello\n")
        with open(target, "w", encoding="utf-8") as f:
            f.write("world\n")

        arun(ReadTool.call(json.dumps({"file_path": source})))
        # Not reading target

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 1,
                        "end_line": 1,
                        "target_file_path": target,
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("Target file has not been read yet", res.output)

    def test_move_start_greater_than_end(self) -> None:
        """Start line must be <= end line."""
        source = os.path.abspath("source4.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("line1\nline2\n")

        arun(ReadTool.call(json.dumps({"file_path": source})))

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 3,
                        "end_line": 1,
                        "target_file_path": "new.txt",
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("start_line must be <= end_line", res.output)

    def test_move_line_out_of_bounds(self) -> None:
        """Line numbers must not exceed file length."""
        source = os.path.abspath("source5.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("line1\nline2\n")

        arun(ReadTool.call(json.dumps({"file_path": source})))

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 1,
                        "end_line": 10,
                        "target_file_path": "new.txt",
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("end_line 10 exceeds file length 2", res.output)

    def test_move_new_file_requires_insert_line_1(self) -> None:
        """Creating new file requires insert_line=1."""
        source = os.path.abspath("source6.txt")
        target = os.path.abspath("nonexistent.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("hello\n")

        arun(ReadTool.call(json.dumps({"file_path": source})))

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 1,
                        "end_line": 1,
                        "target_file_path": target,
                        "insert_line": 5,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("Use insert_line=1 to create new file", res.output)

    def test_move_source_not_exist(self) -> None:
        """Source file must exist."""
        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": "/nonexistent/source.txt",
                        "start_line": 1,
                        "end_line": 1,
                        "target_file_path": "target.txt",
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("Source file does not exist", res.output)

    def test_move_directory_error(self) -> None:
        """Cannot move from or to directories."""
        dir_path = os.path.abspath(".")

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": dir_path,
                        "start_line": 1,
                        "end_line": 1,
                        "target_file_path": "target.txt",
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("Source path is a directory", res.output)

    def test_move_same_file_insert_within_move_range(self) -> None:
        """Cannot insert within the move range for same-file move."""
        file_path = os.path.abspath("samefile.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("1\n2\n3\n4\n5\n")

        arun(ReadTool.call(json.dumps({"file_path": file_path})))

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": file_path,
                        "start_line": 2,
                        "end_line": 4,
                        "target_file_path": file_path,
                        "insert_line": 3,  # Within the cut range
                    }
                )
            )
        )

        self.assertEqual(res.status, "error")
        self.assertIn("insert_line cannot be within the cut range", res.output)

    def test_move_updates_file_tracker(self) -> None:
        """File tracker should be updated after move."""
        source = os.path.abspath("tracked_source.txt")
        target = os.path.abspath("tracked_target.txt")

        with open(source, "w", encoding="utf-8") as f:
            f.write("A\nB\nC\n")

        arun(ReadTool.call(json.dumps({"file_path": source})))

        res = arun(
            MoveTool.call(
                json.dumps(
                    {
                        "source_file_path": source,
                        "start_line": 2,
                        "end_line": 2,
                        "target_file_path": target,
                        "insert_line": 1,
                    }
                )
            )
        )

        self.assertEqual(res.status, "success")

        # Both files should be tracked
        source_status = self.session.file_tracker.get(source)
        target_status = self.session.file_tracker.get(target)

        self.assertIsNotNone(source_status)
        self.assertIsNotNone(target_status)


if __name__ == "__main__":
    unittest.main()
