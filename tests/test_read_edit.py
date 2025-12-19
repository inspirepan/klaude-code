import asyncio
import base64
import contextlib
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in os.sys.path:  # type: ignore
    os.sys.path.insert(0, str(SRC_DIR))  # type: ignore

from klaude_code.core.reminders import at_file_reader_reminder  # noqa: E402
from klaude_code.core.tool import (  # noqa: E402
    EditTool,
    ReadTool,
    ToolContextToken,
    reset_tool_context,
    set_tool_context_from_session,
)
from klaude_code.protocol import model  # noqa: E402
from klaude_code.session.session import Session  # noqa: E402

_TINY_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="


def arun(coro) -> Any:  # type: ignore
    return asyncio.run(coro)  # type: ignore


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.session = Session(work_dir=Path.cwd())
        self._token: ToolContextToken = set_tool_context_from_session(self.session)

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            reset_tool_context(self._token)
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


class TestReadTool(BaseTempDirTest):
    def test_read_basic_and_reminder(self):
        file_path = os.path.abspath("basic.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")
        res = arun(ReadTool.call(json.dumps({"file_path": file_path})))
        self.assertEqual(res.status, "success")
        self.assertIn("1→line1", res.output or "")
        self.assertIn("2→line2", res.output or "")
        # ReadTool should also record a content hash in file_tracker
        status = self.session.file_tracker.get(file_path)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertIsNotNone(status.content_sha256)
        expected = hashlib.sha256(b"line1\nline2\nline3\n").hexdigest()
        self.assertEqual(status.content_sha256, expected)
        # self.assertIn("<system-reminder>", res.output or "")

    def test_read_directory_error(self):
        dir_path = os.path.abspath(".")
        res = arun(ReadTool.call(json.dumps({"file_path": dir_path})))
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>Illegal operation on a directory. read</tool_use_error>",
        )

    def test_read_file_not_exist(self):
        missing = os.path.abspath("missing.txt")
        res = arun(ReadTool.call(json.dumps({"file_path": missing})))
        self.assertEqual(res.status, "error")
        self.assertEqual(res.output, "<tool_use_error>File does not exist.</tool_use_error>")

    def test_read_large_file_truncated(self):
        # Large files are now truncated instead of erroring
        big = os.path.abspath("big.txt")
        with open(big, "w", encoding="utf-8") as f:
            # Write many lines to exceed char limit
            for i in range(5000):
                f.write(f"line{i}\n")
        res = arun(ReadTool.call(json.dumps({"file_path": big})))
        self.assertEqual(res.status, "success")
        # Should be truncated with remaining lines info and reason
        self.assertIn("more lines truncated due to", res.output or "")
        self.assertIn("use offset/limit to read other parts", res.output or "")

    def test_read_offset_beyond(self):
        p = os.path.abspath("short.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("only one line\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p, "offset": 2})))
        self.assertEqual(res.status, "success")
        self.assertIn("shorter than the provided offset (2)", res.output or "")

    def test_read_total_chars_limit_truncates(self):
        # Files exceeding char limit are now truncated instead of erroring
        p = os.path.abspath("manylines.txt")
        with open(p, "w", encoding="utf-8") as f:
            for _ in range(4000):
                f.write("x" * 20 + "\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p})))
        self.assertEqual(res.status, "success")
        output = res.output or ""
        # Should show content and truncation message with char limit reason and total lines
        self.assertIn("1→", output)
        self.assertIn("more lines truncated due to 50000 char limit", output)
        self.assertIn("file has 4000 lines total", output)
        self.assertIn("use offset/limit to read other parts", output)

    def test_read_per_line_truncation(self):
        p = os.path.abspath("longline.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x" * 2100 + "\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p})))
        self.assertEqual(res.status, "success")
        self.assertIn("1→", res.output or "")
        self.assertIn("more 100 characters in this line are truncated", res.output or "")

    def test_read_image_inline_success(self):
        file_path = os.path.abspath("tiny.png")
        with open(file_path, "wb") as image_file:
            image_file.write(base64.b64decode(_TINY_PNG_BASE64))

        res = arun(ReadTool.call(json.dumps({"file_path": file_path})))
        self.assertEqual(res.status, "success")
        self.assertIsNotNone(res.images)
        assert res.images is not None
        self.assertTrue(res.images[0].image_url.url.startswith("data:image/png;base64,"))
        self.assertIn("[image] tiny.png", res.output or "")

    def test_read_image_too_large_error(self):
        file_path = os.path.abspath("large.png")
        oversized = 4 * 1024 * 1024 + 1
        with open(file_path, "wb") as image_file:
            image_file.write(b"0" * oversized)

        res = arun(ReadTool.call(json.dumps({"file_path": file_path})))
        self.assertEqual(res.status, "error")
        self.assertIn("maximum supported size (4.00MB)", res.output or "")


class TestReminders(BaseTempDirTest):
    def test_at_file_reader_reminder_includes_images(self):
        file_path = os.path.abspath("tiny.png")
        with open(file_path, "wb") as image_file:
            image_file.write(base64.b64decode(_TINY_PNG_BASE64))

        self.session.conversation_history.append(model.UserMessageItem(content=f"Please review @{file_path}"))

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.images)
        assert reminder.images is not None
        self.assertTrue(reminder.images[0].image_url.url.startswith("data:image/png;base64,"))
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        self.assertIsNotNone(reminder.at_files[0].images)
        assert reminder.at_files[0].images is not None
        self.assertTrue(reminder.at_files[0].images[0].image_url.url.startswith("data:image/png;base64,"))

    def test_at_file_reader_reminder_supports_paths_with_spaces(self):
        # Create a file whose directory and filename both contain spaces
        dir_path = Path("dir with spaces")
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = (dir_path / "my file.txt").resolve()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello world\n")

        # Use quoted @-pattern so that spaces are preserved
        self.session.conversation_history.append(model.UserMessageItem(content=f'Please review @"{file_path}"'))

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        self.assertEqual(len(reminder.at_files), 1)
        at_file = reminder.at_files[0]
        self.assertEqual(at_file.path, str(file_path))
        self.assertIn("hello world", at_file.result)

    def test_at_file_reader_reminder_preserves_filename_case(self):
        # Create a file with uppercase letters in the name
        file_path = os.path.abspath("README.md")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("READ ME\n")

        # Reference the file using @ with the same casing
        self.session.conversation_history.append(model.UserMessageItem(content=f"Please review @{file_path}"))

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        self.assertEqual(len(reminder.at_files), 1)
        at_file = reminder.at_files[0]
        # Path string should preserve the filename casing (e.g. README.md, not readme.md)
        self.assertTrue(at_file.path.endswith("README.md"))
        self.assertIn("READ ME", at_file.result)

    def test_at_file_reader_reminder_ignores_mid_word_at_symbols(self):
        file_path = os.path.abspath("bar.com")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("should not be read\n")

        self.session.conversation_history.append(
            model.UserMessageItem(content="Contact me via foo@bar.com for details.")
        )

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNone(reminder)

    def test_at_file_reader_reminder_recursive_loading(self):
        # Create nested files: main.md -> sub.md -> leaf.txt
        leaf_path = os.path.abspath("leaf.txt")
        with open(leaf_path, "w", encoding="utf-8") as f:
            f.write("leaf content\n")

        sub_path = os.path.abspath("sub.md")
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(f"sub content\n@{leaf_path}\n")

        main_path = os.path.abspath("main.md")
        with open(main_path, "w", encoding="utf-8") as f:
            f.write(f"main content\n@{sub_path}\n")

        self.session.conversation_history.append(model.UserMessageItem(content=f"@{main_path}"))

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        # Should load all 3 files recursively
        self.assertEqual(len(reminder.at_files), 3)
        at_files_by_path = {at.path: at for at in reminder.at_files}
        self.assertIn(main_path, at_files_by_path)
        self.assertIn(sub_path, at_files_by_path)
        self.assertIn(leaf_path, at_files_by_path)
        # Verify mentioned_in chain
        self.assertIsNone(at_files_by_path[main_path].mentioned_in)
        self.assertEqual(at_files_by_path[sub_path].mentioned_in, main_path)
        self.assertEqual(at_files_by_path[leaf_path].mentioned_in, sub_path)

    def test_at_file_reader_reminder_recursive_prevents_cycles(self):
        # Create files that reference each other: a.md <-> b.md
        a_path = os.path.abspath("a.md")
        b_path = os.path.abspath("b.md")

        with open(a_path, "w", encoding="utf-8") as f:
            f.write(f"file a\n@{b_path}\n")
        with open(b_path, "w", encoding="utf-8") as f:
            f.write(f"file b\n@{a_path}\n")

        self.session.conversation_history.append(model.UserMessageItem(content=f"@{a_path}"))

        # Should not hang or error due to cycle
        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        # Should load both files exactly once
        self.assertEqual(len(reminder.at_files), 2)

    def test_at_file_reader_reminder_recursive_relative_path(self):
        # Create subdir/child.md that references ../sibling.txt
        subdir = Path("subdir")
        subdir.mkdir(exist_ok=True)

        sibling_path = os.path.abspath("sibling.txt")
        with open(sibling_path, "w", encoding="utf-8") as f:
            f.write("sibling content\n")

        child_path = (subdir / "child.md").resolve()
        with open(child_path, "w", encoding="utf-8") as f:
            f.write("child content\n@../sibling.txt\n")

        self.session.conversation_history.append(model.UserMessageItem(content=f"@{child_path}"))

        reminder = arun(at_file_reader_reminder(self.session))
        self.assertIsNotNone(reminder)
        assert reminder is not None
        self.assertIsNotNone(reminder.at_files)
        assert reminder.at_files is not None
        # Should load both files
        self.assertEqual(len(reminder.at_files), 2)
        paths = [at.path for at in reminder.at_files]
        self.assertIn(str(child_path), paths)
        self.assertIn(sibling_path, paths)


class TestEditTool(BaseTempDirTest):
    def test_edit_requires_read_first(self):
        p = os.path.abspath("edit.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("第一行\n重复行\n重复行\n第五行\n")
        # No prior read on this session
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "第一行",
                        "new_string": "修改后的第一行",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "File has not been read yet. Read it first before writing to it.",
        )

    def test_edit_single_replacement_and_snippet(self):
        p = os.path.abspath("single.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("第一行\n第二行\n")
        # Read to track
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "第一行",
                        "new_string": "修改后的行",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "success")
        self.assertIn("Here's the result of running `cat -n`", res.output or "")
        self.assertIn("1→修改后的行", res.output or "")

    def test_edit_duplicates_require_replace_all_or_unique(self):
        p = os.path.abspath("dups.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("a\n重复行\n重复行\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "重复行",
                        "new_string": "修改后的行",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertIn("Found 2 matches", res.output or "")
        self.assertIn("String: 重复行", res.output or "")

        # Now replace_all
        res2 = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "重复行",
                        "new_string": "修改后的行",
                        "replace_all": True,
                    }
                )
            )
        )
        self.assertEqual(res2.status, "success")
        self.assertIn("All occurrences of '重复行' were successfully replaced", res2.output or "")

    def test_edit_not_found_and_same_string(self):
        p = os.path.abspath("notfound.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))

        # not found
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "不存在的内容",
                        "new_string": "x",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>String to replace not found in file.\nString: 不存在的内容</tool_use_error>",
        )

        # same string
        res2 = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "X",
                        "new_string": "X",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res2.status, "error")
        self.assertEqual(
            res2.output,
            "<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>",
        )

    def test_edit_rejects_empty_old_string(self):
        p = os.path.abspath("newfile.txt")
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "",
                        "new_string": "hello\n",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>old_string must not be empty for Edit. To create or overwrite a file, use the Write tool instead.</tool_use_error>",
        )

    def test_edit_directory_error(self):
        dir_path = os.path.abspath(".")
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": dir_path,
                        "old_string": "x",
                        "new_string": "y",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>Illegal operation on a directory. edit</tool_use_error>",
        )

    def test_edit_mtime_mismatch(self):
        p = os.path.abspath("mtime.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        orig_mtime_ns = os.stat(p).st_mtime_ns
        # external modification
        with open(p, "a", encoding="utf-8") as f:
            f.write("world\n")
        # Restore mtime to original to ensure hash-based detection is used.
        os.utime(p, ns=(orig_mtime_ns, orig_mtime_ns))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "hello\nworld\n",
                        "new_string": "HELLO\nWORLD\n",
                        "replace_all": False,
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "File has been modified externally. Either by user or a linter. Read it first before writing to it.",
        )


if __name__ == "__main__":
    unittest.main()
