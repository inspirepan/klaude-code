import asyncio
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in os.sys.path:  # type: ignore
    os.sys.path.insert(0, str(SRC_DIR))  # type: ignore

from klaude_code.core.reminders import at_file_reader_reminder  # noqa: E402
from klaude_code.core.tool.file.edit_tool import EditTool  # noqa: E402
from klaude_code.core.tool.file.multi_edit_tool import MultiEditTool  # noqa: E402
from klaude_code.core.tool.file.read_tool import ReadTool  # noqa: E402
from klaude_code.core.tool.tool_context import ToolContextToken  # noqa: E402
from klaude_code.core.tool.tool_context import reset_tool_context, set_tool_context_from_session
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
        try:
            reset_tool_context(self._token)
        except Exception:
            pass
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

    def test_read_size_limit_error(self):
        big = os.path.abspath("big.bin")
        with open(big, "wb") as f:
            f.write(b"a" * (256 * 1024 + 10))
        res = arun(ReadTool.call(json.dumps({"file_path": big})))
        self.assertEqual(res.status, "error")
        self.assertIn("maximum allowed size (256KB)", res.output or "")

    def test_read_offset_beyond(self):
        p = os.path.abspath("short.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("only one line\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p, "offset": 2})))
        self.assertEqual(res.status, "success")
        self.assertIn("shorter than the provided offset (2)", res.output or "")

    def test_read_total_chars_limit(self):
        p = os.path.abspath("manylines.txt")
        with open(p, "w", encoding="utf-8") as f:
            for _ in range(4000):
                f.write("x" * 20 + "\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p})))
        self.assertEqual(res.status, "error")
        self.assertIn("maximum allowed tokens (60000)", res.output or "")

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
        # external modification
        with open(p, "a", encoding="utf-8") as f:
            f.write("world\n")
        # ensure mtime changes
        time.sleep(0.01)
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


class TestMultiEditTool(BaseTempDirTest):
    def test_multiedit_requires_read_first(self):
        p = os.path.abspath("multi.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("第一行：需要修改\n第二行：也要修改\n第三行：不变\n第四行：同样需要修改\n")
        args = {
            "file_path": p,
            "edits": [
                {"old_string": "第一行：需要修改", "new_string": "第一行：已修改"},
                {"old_string": "第二行：也要修改", "new_string": "第二行：已修改"},
            ],
        }
        res = arun(MultiEditTool.call(json.dumps(args)))
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "File has not been read yet. Read it first before writing to it.",
        )

    def test_multiedit_success_sequence(self):
        p = os.path.abspath("multi_ok.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("第一行：需要修改\n第二行：也要修改\n第三行：不变\n第四行：同样需要修改\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        args = {
            "file_path": p,
            "edits": [
                {"old_string": "第一行：需要修改", "new_string": "第一行：已修改"},
                {"old_string": "第二行：也要修改", "new_string": "第二行：已修改"},
                {"old_string": "第四行：同样需要修改", "new_string": "第四行：已修改"},
            ],
        }
        res = arun(MultiEditTool.call(json.dumps(args)))
        self.assertEqual(res.status, "success")
        self.assertIn(f"Applied 3 edits to {p}:", res.output or "")
        self.assertIn('1. Replaced "第一行：需要修改" with "第一行：已修改"', res.output or "")
        self.assertIn('2. Replaced "第二行：也要修改" with "第二行：已修改"', res.output or "")
        self.assertIn('3. Replaced "第四行：同样需要修改" with "第四行：已修改"', res.output or "")

    def test_multiedit_validation_failure_mid_sequence(self):
        p = os.path.abspath("multi_fail.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("abc\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        args = {
            "file_path": p,
            "edits": [
                {"old_string": "abc", "new_string": "def"},
                {
                    "old_string": "abc",
                    "new_string": "xyz",
                },  # not found after first edit
            ],
        }
        res = arun(MultiEditTool.call(json.dumps(args)))
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>String to replace not found in file.\nString: abc</tool_use_error>",
        )

    def test_multiedit_directory_error(self):
        dir_path = os.path.abspath(".")
        res = arun(
            MultiEditTool.call(
                json.dumps(
                    {
                        "file_path": dir_path,
                        "edits": [{"old_string": "a", "new_string": "b"}],
                    }
                )
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "<tool_use_error>Illegal operation on a directory. multi_edit</tool_use_error>",
        )

    def test_multiedit_creation_then_edit(self):
        p = os.path.abspath("create_seq.txt")
        args = {
            "file_path": p,
            "edits": [
                {"old_string": "", "new_string": "Line1\n"},
                {"old_string": "Line1", "new_string": "Line1 changed"},
            ],
        }
        res = arun(MultiEditTool.call(json.dumps(args)))
        self.assertEqual(res.status, "success")
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Line1 changed", content)

    def test_multiedit_mtime_mismatch(self):
        p = os.path.abspath("multi_mtime.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p})))
        # external modification
        with open(p, "a", encoding="utf-8") as f:
            f.write("world\n")
        time.sleep(0.01)
        args = {
            "file_path": p,
            "edits": [{"old_string": "hello\nworld\n", "new_string": "X\nY\n"}],
        }
        res = arun(MultiEditTool.call(json.dumps(args)))
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output,
            "File has been modified externally. Either by user or a linter. Read it first before writing to it.",
        )


if __name__ == "__main__":
    unittest.main()
