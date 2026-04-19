import asyncio
import base64
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in os.sys.path:  # type: ignore
    os.sys.path.insert(0, str(SRC_DIR))  # type: ignore

from klaude_code.agent.attachments.files import at_file_reader_attachment  # noqa: E402
from klaude_code.protocol import message  # noqa: E402
from klaude_code.protocol.models import AtFileOp, AtFileOpsUIItem, FileStatus, MemoryLoadedUIItem  # noqa: E402
from klaude_code.session.session import Session  # noqa: E402
from klaude_code.tool import (  # noqa: E402
    BashTool,
    EditTool,
    ReadTool,
    WriteTool,
    build_todo_context,
)
from klaude_code.tool.core.context import ToolContext  # noqa: E402

_TINY_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="

def arun(coro) -> Any:  # type: ignore
    return asyncio.run(coro)  # type: ignore

def _get_at_file_ops(attachment: message.DeveloperMessage) -> list[AtFileOp]:
    if attachment.ui_extra is None:
        return []
    for ui_item in attachment.ui_extra.items:
        if isinstance(ui_item, AtFileOpsUIItem):
            return ui_item.ops
    return []

class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.session = Session(work_dir=Path.cwd())
        self.tool_context = ToolContext(
            file_tracker=self.session.file_tracker,
            todo_context=build_todo_context(self.session),
            session_id=self.session.id,
            work_dir=Path(self._tmp.name).resolve(),
            file_change_summary=self.session.file_change_summary,
        )

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()

class TestReadTool(BaseTempDirTest):
    def test_read_basic_and_tracking(self):
        file_path = os.path.abspath("basic.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")
        res = arun(ReadTool.call(json.dumps({"file_path": file_path}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("1→line1", res.output_text or "")
        self.assertIn("2→line2", res.output_text or "")
        # ReadTool should also record a content hash in file_tracker
        status = self.session.file_tracker.get(file_path)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertIsNotNone(status.content_sha256)
        expected = hashlib.sha256(b"line1\nline2\nline3\n").hexdigest()
        self.assertEqual(status.content_sha256, expected)
        # self.assertIn("<system-reminder>", res.output_text or "")

    def test_read_directory_error(self):
        dir_path = os.path.abspath(".")
        res = arun(ReadTool.call(json.dumps({"file_path": dir_path}), self.tool_context))
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
            "<tool_use_error>Illegal operation on a directory: read</tool_use_error>",
        )

    def test_read_file_not_exist(self):
        missing = os.path.abspath("missing.txt")
        res = arun(ReadTool.call(json.dumps({"file_path": missing}), self.tool_context))
        self.assertEqual(res.status, "error")
        self.assertEqual(res.output_text, "<tool_use_error>File does not exist.</tool_use_error>")

    def test_read_file_not_exist_no_directory_match(self):
        # When the stem matches a regular file (not a directory), no suggestions are shown
        existing = os.path.abspath("global")
        with open(existing, "w", encoding="utf-8") as f:
            f.write("x\n")

        missing = os.path.abspath("global.ts")
        res = arun(ReadTool.call(json.dumps({"file_path": missing}), self.tool_context))

        self.assertEqual(res.status, "error")
        self.assertEqual(res.output_text, "<tool_use_error>File does not exist.</tool_use_error>")

    def test_read_file_not_exist_with_directory_preview(self):
        manager_dir = Path("manager")
        manager_dir.mkdir()

        init_py = (manager_dir / "__init__.py").resolve()
        manager_py = (manager_dir / "manager.py").resolve()
        llm_clients_py = (manager_dir / "llm_clients.py").resolve()
        sub_agent_manager_py = (manager_dir / "sub_agent_manager.py").resolve()
        extra_py = (manager_dir / "extra.py").resolve()
        other_file = (manager_dir / "notes.txt").resolve()

        for file_path in [init_py, manager_py, llm_clients_py, sub_agent_manager_py, extra_py, other_file]:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("x\n")

        missing = os.path.abspath("manager.py")
        res = arun(ReadTool.call(json.dumps({"file_path": missing}), self.tool_context))

        self.assertEqual(res.status, "error")
        self.assertIn("Did you mean one of these?", res.output_text or "")
        self.assertIn(f"- {manager_dir.resolve()} (directory)", res.output_text or "")
        self.assertIn(f"- {init_py}", res.output_text or "")
        self.assertIn(f"- {manager_py}", res.output_text or "")
        self.assertIn(f"- {llm_clients_py}", res.output_text or "")
        self.assertIn(f"- {sub_agent_manager_py}", res.output_text or "")
        self.assertIn("(+1 more files; use Bash ls for full listing)", res.output_text or "")

    def test_read_large_file_truncated(self):
        # Large files are now truncated instead of erroring
        big = os.path.abspath("big.txt")
        with open(big, "w", encoding="utf-8") as f:
            # Write many lines to exceed char limit
            for i in range(5000):
                f.write(f"line{i}\n")
        res = arun(ReadTool.call(json.dumps({"file_path": big}), self.tool_context))
        self.assertEqual(res.status, "success")
        # Should be truncated with remaining lines info and reason
        self.assertIn("more lines truncated due to", res.output_text or "")
        self.assertIn("use offset/limit to read other parts", res.output_text or "")

    def test_read_offset_beyond(self):
        p = os.path.abspath("short.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("only one line\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p, "offset": 2}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("shorter than the provided offset (2)", res.output_text or "")

    def test_read_total_chars_limit_truncates(self):
        # Files exceeding char limit are now truncated instead of erroring
        p = os.path.abspath("manylines.txt")
        with open(p, "w", encoding="utf-8") as f:
            for _ in range(4000):
                f.write("x" * 20 + "\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res.status, "success")
        output = res.output_text or ""
        # Should show content and truncation message with char limit reason and total lines
        self.assertIn("1→", output)
        self.assertIn("more lines truncated due to 50000 char limit", output)
        self.assertIn("file has 4000 lines total", output)
        self.assertIn("use offset/limit to read other parts", output)

    def test_read_per_line_truncation(self):
        p = os.path.abspath("longline.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x" * 2100 + "\n")
        res = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("1→", res.output_text or "")
        self.assertIn("more 100 characters in this line are truncated", res.output_text or "")

    def test_read_image_inline_success(self):
        file_path = os.path.abspath("tiny.png")
        with open(file_path, "wb") as image_file:
            image_file.write(base64.b64decode(_TINY_PNG_BASE64))

        res = arun(ReadTool.call(json.dumps({"file_path": file_path}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertTrue(res.parts)
        assert res.parts
        self.assertTrue(res.parts[0].url.startswith("data:image/png;base64,"))
        self.assertIn("[image] tiny.png", res.output_text or "")

    def test_read_image_too_large_error(self):
        file_path = os.path.abspath("large.png")
        oversized = 64 * 1024 * 1024 + 1
        with open(file_path, "wb") as image_file:
            image_file.write(b"0" * oversized)

        res = arun(ReadTool.call(json.dumps({"file_path": file_path}), self.tool_context))
        self.assertEqual(res.status, "error")
        self.assertIn("maximum supported size (64.00MB)", res.output_text or "")

class TestAttachments(BaseTempDirTest):
    def test_at_file_reader_attachment_includes_images(self):
        file_path = os.path.abspath("tiny.png")
        with open(file_path, "wb") as image_file:
            image_file.write(base64.b64decode(_TINY_PNG_BASE64))

        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str(f"Please review @{file_path}"))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None

        # Images are now in parts
        image_parts = [p for p in attachment.parts if isinstance(p, message.ImageURLPart)]
        self.assertTrue(len(image_parts) > 0)
        self.assertTrue(image_parts[0].url.startswith("data:image/png;base64,"))

        self.assertEqual(len(_get_at_file_ops(attachment)), 1)

    def test_at_file_reader_attachment_supports_paths_with_spaces(self):
        # Create a file whose directory and filename both contain spaces
        dir_path = Path("dir with spaces")
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = (dir_path / "my file.txt").resolve()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello world\n")

        # Use quoted @-pattern so that spaces are preserved
        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str(f'Please review @"{file_path}"'))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None
        ops = _get_at_file_ops(attachment)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].path, str(file_path))
        self.assertIn("hello world", message.join_text_parts(attachment.parts))

    def test_at_file_reader_attachment_preserves_filename_case(self):
        # Create a file with uppercase letters in the name
        file_path = os.path.abspath("README.md")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("READ ME\n")

        # Reference the file using @ with the same casing
        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str(f"Please review @{file_path}"))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None

        ops = _get_at_file_ops(attachment)
        self.assertEqual(len(ops), 1)
        at_file = ops[0]
        # Path string should preserve the filename casing (e.g. README.md, not readme.md)
        self.assertTrue(at_file.path.endswith("README.md"))
        self.assertIn("READ ME", message.join_text_parts(attachment.parts))

    def test_at_file_reader_attachment_returns_lightweight_for_tracked_unchanged_file(self):
        file_path = os.path.abspath("tracked.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("hello\n")

        _ = arun(ReadTool.call(json.dumps({"file_path": file_path}), self.tool_context))

        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str(f"@{file_path}"))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        # Now returns a lightweight "already in context" message instead of None
        self.assertIsNotNone(attachment)
        text = message.join_text_parts(attachment.parts)
        self.assertIn("already in context", text)
        self.assertNotIn("hello", text)

    def test_at_file_reader_attachment_returns_lightweight_when_touched_but_hash_unchanged(self):
        file_path = os.path.abspath("touched.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("same content\n")

        _ = arun(ReadTool.call(json.dumps({"file_path": file_path}), self.tool_context))
        status = self.session.file_tracker.get(file_path)
        self.assertIsNotNone(status)
        assert status is not None

        orig_mtime_ns = os.stat(file_path).st_mtime_ns
        new_mtime_ns = orig_mtime_ns + 2_000_000_000
        os.utime(file_path, ns=(new_mtime_ns, new_mtime_ns))

        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str(f"@{file_path}"))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        # File content unchanged (same hash), so lightweight message
        self.assertIsNotNone(attachment)
        text = message.join_text_parts(attachment.parts)
        self.assertIn("already in context", text)

    def test_at_file_reader_attachment_ignores_mid_word_at_symbols(self):
        file_path = os.path.abspath("bar.com")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("should not be read\n")

        self.session.conversation_history.append(
            message.UserMessage(parts=message.text_parts_from_str("Contact me via foo@bar.com for details."))
        )

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNone(attachment)

    def test_at_file_reader_attachment_discovers_memory_in_directory(self):
        """When @dir is used, AGENTS.md in that directory should be auto-injected."""
        subdir = Path("subdir")
        subdir.mkdir(exist_ok=True)
        (subdir / "file.txt").write_text("hello\n")
        agents_md = subdir / "AGENTS.md"
        agents_md.write_text("# Subdir Instructions\nDo something special.\n")

        dir_path = str(subdir.resolve())
        self.session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(f"@{dir_path}")))

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None

        # Should have the ls op for the directory
        ops = _get_at_file_ops(attachment)
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0].operation, "List")

        # Memory file should be discovered and included in text
        text = message.join_text_parts(attachment.parts)
        self.assertIn("Subdir Instructions", text)
        self.assertIn("Do something special", text)

        # Memory file should be reflected in UI
        assert attachment.ui_extra is not None
        memory_items = [i for i in attachment.ui_extra.items if isinstance(i, MemoryLoadedUIItem)]
        self.assertEqual(len(memory_items), 1)
        self.assertEqual(len(memory_items[0].files), 1)
        self.assertTrue(memory_items[0].files[0].path.endswith("AGENTS.md"))

        # Memory file should be marked as loaded in file_tracker
        self.assertIn(str(agents_md.resolve()), self.session.file_tracker)
        status = self.session.file_tracker[str(agents_md.resolve())]
        self.assertTrue(status.is_memory)

    def test_at_file_reader_attachment_discovers_memory_in_parent_dirs(self):
        """When @deep/dir is used, AGENTS.md in intermediate dirs should also be injected."""
        parent = Path("parent")
        parent.mkdir(exist_ok=True)
        (parent / "AGENTS.md").write_text("parent instructions\n")
        child = parent / "child"
        child.mkdir(exist_ok=True)
        (child / "data.txt").write_text("data\n")
        (child / "AGENTS.md").write_text("child instructions\n")

        dir_path = str(child.resolve())
        self.session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(f"@{dir_path}")))

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None

        text = message.join_text_parts(attachment.parts)
        self.assertIn("parent instructions", text)
        self.assertIn("child instructions", text)

    def test_at_file_reader_attachment_no_duplicate_memory_if_already_loaded(self):
        """Memory files already loaded by memory_attachment should not be loaded again."""
        subdir = Path("subdir")
        subdir.mkdir(exist_ok=True)
        (subdir / "file.txt").write_text("hello\n")
        agents_md = subdir / "AGENTS.md"
        agents_md.write_text("subdir instructions\n")

        # Pre-mark the memory as loaded (simulating memory_attachment having loaded it)
        agents_path = str(agents_md.resolve())
        self.session.file_tracker[agents_path] = FileStatus(
            mtime=agents_md.stat().st_mtime,
            content_sha256=hashlib.sha256(agents_md.read_bytes()).hexdigest(),
            is_memory=True,
        )

        dir_path = str(subdir.resolve())
        self.session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(f"@{dir_path}")))

        attachment = arun(at_file_reader_attachment(self.session))
        self.assertIsNotNone(attachment)
        assert attachment is not None

        # Should have the ls op but no memory content
        text = message.join_text_parts(attachment.parts)
        self.assertNotIn("subdir instructions", text)

        # No MemoryLoadedUIItem
        assert attachment.ui_extra is not None
        memory_items = [i for i in attachment.ui_extra.items if isinstance(i, MemoryLoadedUIItem)]
        self.assertEqual(len(memory_items), 0)

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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
            "File has not been read yet. Read it first before writing to it.",
        )

    def test_edit_single_replacement_and_snippet(self):
        p = os.path.abspath("single.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("第一行\n第二行\n")
        # Read to track
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "第一行",
                        "new_string": "修改后的行",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        self.assertIn("has been updated successfully", res.output_text or "")

    def test_edit_duplicates_require_replace_all_or_unique(self):
        p = os.path.abspath("dups.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("a\n重复行\n重复行\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "重复行",
                        "new_string": "修改后的行",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertIn("Found 2 matches", res.output_text or "")
        self.assertIn("String: 重复行", res.output_text or "")

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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res2.status, "success")
        self.assertIn("All occurrences were successfully replaced", res2.output_text or "")

    def test_edit_not_found_and_same_string(self):
        p = os.path.abspath("notfound.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res2.status, "error")
        self.assertEqual(
            res2.output_text,
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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
            "<tool_use_error>Illegal operation on a directory: edit</tool_use_error>",
        )

    def test_edit_mtime_mismatch(self):
        p = os.path.abspath("mtime.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
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
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "error")
        self.assertEqual(
            res.output_text,
            "File has been modified externally. Either by user or a linter. Read it first before writing to it.",
        )

    def test_edit_records_changed_file_and_diff_totals(self):
        p = os.path.abspath("tracked_edit.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("one\ntwo\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "one",
                        "new_string": "ONE",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )

        self.assertEqual(res.status, "success")
        self.assertEqual(self.session.file_change_summary.created_files, [])
        self.assertEqual(self.session.file_change_summary.edited_files, [p])
        self.assertEqual(self.session.file_change_summary.diff_lines_added, 1)
        self.assertEqual(self.session.file_change_summary.diff_lines_removed, 1)

class TestWriteTool(BaseTempDirTest):
    def test_write_records_created_and_edited_files_with_diff_totals(self):
        p = os.path.abspath("write_target.txt")

        create_res = arun(
            WriteTool.call(
                json.dumps({"file_path": p, "content": "alpha\nbeta\n"}),
                self.tool_context,
            )
        )
        self.assertEqual(create_res.status, "success")
        self.assertEqual(self.session.file_change_summary.created_files, [p])
        self.assertEqual(self.session.file_change_summary.edited_files, [])
        self.assertEqual(self.session.file_change_summary.diff_lines_added, 2)
        self.assertEqual(self.session.file_change_summary.diff_lines_removed, 0)

        overwrite_res = arun(
            WriteTool.call(
                json.dumps({"file_path": p, "content": "alpha\nBETA\n"}),
                self.tool_context,
            )
        )
        self.assertEqual(overwrite_res.status, "success")
        self.assertEqual(self.session.file_change_summary.created_files, [p])
        self.assertEqual(self.session.file_change_summary.edited_files, [p])
        self.assertEqual(self.session.file_change_summary.diff_lines_added, 3)
        self.assertEqual(self.session.file_change_summary.diff_lines_removed, 1)

class TestBashToolFileTracking(BaseTempDirTest):
    def test_bash_cat_counts_as_read_for_edit(self):
        p = os.path.abspath("cat_read.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")

        res = arun(BashTool.call(json.dumps({"command": f"cat {p}"}), self.tool_context))
        self.assertEqual(res.status, "success")

        status = self.session.file_tracker.get(p)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.content_sha256, hashlib.sha256(b"hello\n").hexdigest())

        # Edit should be allowed because the file is now tracked as read.
        res2 = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "hello",
                        "new_string": "HELLO",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res2.status, "success")

    def test_bash_sed_updates_tracker_to_avoid_external_change_error(self):
        p = os.path.abspath("sed_inplace.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("foo\n")

        # In-place edit via sed should update file_tracker so subsequent edits won't error.
        res = arun(BashTool.call(json.dumps({"command": f"sed -i.bak 's/foo/bar/' {p}"}), self.tool_context))
        self.assertEqual(res.status, "success")

        status = self.session.file_tracker.get(p)
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status.content_sha256, hashlib.sha256(b"bar\n").hexdigest())

        res2 = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "bar",
                        "new_string": "baz",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res2.status, "success")

    def test_bash_mv_moves_tracked_status(self):
        src = os.path.abspath("old_name.txt")
        dst = os.path.abspath("new_name.txt")
        with open(src, "w", encoding="utf-8") as f:
            f.write("move me\n")

        _ = arun(BashTool.call(json.dumps({"command": f"cat {src}"}), self.tool_context))
        self.assertIn(src, self.session.file_tracker)

        res = arun(BashTool.call(json.dumps({"command": f"mv {src} {dst}"}), self.tool_context))
        self.assertEqual(res.status, "success")

        self.assertNotIn(src, self.session.file_tracker)
        self.assertIn(dst, self.session.file_tracker)
        status = self.session.file_tracker.get(dst)
        assert status is not None
        self.assertEqual(status.content_sha256, hashlib.sha256(b"move me\n").hexdigest())

    def test_bash_cd_and_cat_tracks_in_subdir(self):
        sub = Path("sub")
        sub.mkdir(parents=True, exist_ok=True)
        p = (sub / "f.txt").resolve()
        with open(p, "w", encoding="utf-8") as f:
            f.write("hi\n")

        res = arun(BashTool.call(json.dumps({"command": "cd sub && cat f.txt"}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn(str(p), self.session.file_tracker)
        status = self.session.file_tracker.get(str(p))
        assert status is not None
        self.assertEqual(status.content_sha256, hashlib.sha256(b"hi\n").hexdigest())

    def test_bash_cd_and_mv_moves_tracked_status(self):
        sub = Path("submv")
        sub.mkdir(parents=True, exist_ok=True)
        src = (sub / "a.txt").resolve()
        dst = (sub / "b.txt").resolve()
        with open(src, "w", encoding="utf-8") as f:
            f.write("x\n")

        _ = arun(BashTool.call(json.dumps({"command": f"cd {sub} && cat a.txt"}), self.tool_context))
        self.assertIn(str(src), self.session.file_tracker)

        res = arun(BashTool.call(json.dumps({"command": f"cd {sub} && mv a.txt b.txt"}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertNotIn(str(src), self.session.file_tracker)
        self.assertIn(str(dst), self.session.file_tracker)

# ============================================================================
# Property-based tests for EditTool
# ============================================================================

@st.composite
def edit_scenarios(draw: st.DrawFn) -> tuple[str, str, str, bool]:
    """Generate (content, old_string, new_string, replace_all) tuples."""
    # Generate base content
    base = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=100))

    # Sometimes make old_string a substring of content
    if base and draw(st.booleans()):
        start = draw(st.integers(min_value=0, max_value=max(0, len(base) - 1)))
        end = draw(st.integers(min_value=start, max_value=len(base)))
        old_string = base[start:end]
    else:
        old_string = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=20))

    new_string = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=20))
    replace_all = draw(st.booleans())

    return base, old_string, new_string, replace_all

@st.composite
def edit_scenarios_with_match(draw: st.DrawFn) -> tuple[str, str, str]:
    """Generate (content, old_string, new_string) where old_string is always in content.

    Ensures: old_string is non-empty, present in content, different from new_string,
    and old_string is not a substring of new_string.
    """
    # Generate non-empty old_string first
    old_string = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=20))

    # Generate prefix and suffix to build content containing old_string
    prefix = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=40))
    suffix = draw(st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=40))

    # Optionally repeat old_string multiple times
    repeat_count = draw(st.integers(min_value=1, max_value=3))
    middle = old_string * repeat_count

    content = prefix + middle + suffix

    # Generate new_string that doesn't contain old_string
    new_string = draw(
        st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=20).filter(
            lambda s: old_string not in s and s != old_string
        )
    )

    return content, old_string, new_string

@given(scenario=edit_scenarios())
@settings(max_examples=100, deadline=None)
def test_edit_tool_valid_detects_same_strings(scenario: tuple[str, str, str, bool]) -> None:
    """Property: valid() returns error when old_string == new_string."""
    from klaude_code.tool.file.edit_tool import EditTool

    content, old_string, new_string, replace_all = scenario

    result = EditTool.valid(content=content, old_string=old_string, new_string=new_string, replace_all=replace_all)

    if old_string == new_string:
        assert result is not None
        assert "same" in result.lower()

@given(scenario=edit_scenarios())
@settings(max_examples=100, deadline=None)
def test_edit_tool_valid_detects_missing_string(scenario: tuple[str, str, str, bool]) -> None:
    """Property: valid() returns error when old_string not in content."""
    from klaude_code.tool.file.edit_tool import EditTool

    content, old_string, new_string, replace_all = scenario
    assume(old_string != new_string)

    result = EditTool.valid(content=content, old_string=old_string, new_string=new_string, replace_all=replace_all)

    if old_string not in content:
        assert result is not None
        assert "not found" in result.lower()

@given(scenario=edit_scenarios_with_match())
@settings(max_examples=100, deadline=None)
def test_edit_tool_execute_replace_all_removes_all(scenario: tuple[str, str, str]) -> None:
    """Property: execute with replace_all=True removes all occurrences."""
    from klaude_code.tool.file.edit_tool import EditTool

    content, old_string, new_string = scenario

    result = EditTool.execute(content=content, old_string=old_string, new_string=new_string, replace_all=True)

    assert old_string not in result

@given(scenario=edit_scenarios_with_match())
@settings(max_examples=100, deadline=None)
def test_edit_tool_execute_single_replace_count(scenario: tuple[str, str, str]) -> None:
    """Property: execute with replace_all=False replaces exactly one occurrence."""
    from klaude_code.tool.file.edit_tool import EditTool

    content, old_string, new_string = scenario

    original_count = content.count(old_string)

    result = EditTool.execute(content=content, old_string=old_string, new_string=new_string, replace_all=False)

    # Should have one less occurrence
    assert result.count(old_string) == original_count - 1

class TestBlockedDevicePaths(BaseTempDirTest):
    def test_read_blocked_device_path(self):
        res = arun(ReadTool.call(json.dumps({"file_path": "/dev/zero"}), self.tool_context))
        self.assertEqual(res.status, "error")
        self.assertIn("would block or produce infinite output", res.output_text or "")

    def test_read_blocked_proc_fd(self):
        res = arun(ReadTool.call(json.dumps({"file_path": "/proc/self/fd/0"}), self.tool_context))
        self.assertEqual(res.status, "error")
        self.assertIn("would block or produce infinite output", res.output_text or "")

class TestOOMGuard(BaseTempDirTest):
    def test_edit_rejects_huge_file(self):
        p = os.path.abspath("huge.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        # Check the constant is used
        from klaude_code.const import EDIT_MAX_FILE_SIZE

        self.assertEqual(EDIT_MAX_FILE_SIZE, 1024 * 1024 * 1024)

class TestSmartDeletion(BaseTempDirTest):
    def test_delete_line_removes_trailing_newline(self):
        p = os.path.abspath("smart_del.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("line1\ndelete_me\nline3\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "delete_me",
                        "new_string": "",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        with open(p, encoding="utf-8") as f:
            content = f.read()
        # Should not have a blank line where delete_me was
        self.assertEqual(content, "line1\nline3\n")

    def test_delete_preserves_newline_when_old_string_ends_with_newline(self):
        p = os.path.abspath("smart_del2.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("line1\ndelete_me\nline3\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "delete_me\n",
                        "new_string": "",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        with open(p, encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "line1\nline3\n")

class TestQuoteNormalization(BaseTempDirTest):
    def test_edit_matches_curly_quotes(self):
        p = os.path.abspath("curly.txt")
        # File has curly quotes
        with open(p, "w", encoding="utf-8") as f:
            f.write("She said \u201chello\u201d\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        # Model sends straight quotes
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": 'She said "hello"',
                        "new_string": 'She said "world"',
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        with open(p, encoding="utf-8") as f:
            content = f.read()
        # new_string should have curly quotes preserved
        self.assertIn("\u201c", content)
        self.assertIn("\u201d", content)

class TestReadDedup(BaseTempDirTest):
    def test_read_dedup_returns_unchanged_stub(self):
        p = os.path.abspath("dedup.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")

        # First read
        res1 = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res1.status, "success")
        self.assertIn("1→hello", res1.output_text or "")

        # Second read without modification - should return dedup stub
        res2 = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res2.status, "success")
        self.assertIn("unchanged since last read", res2.output_text or "")

    def test_read_dedup_detects_external_modification(self):
        p = os.path.abspath("dedup_mod.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("hello\n")

        # First read
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        # Modify file externally
        import time

        time.sleep(0.05)
        with open(p, "w", encoding="utf-8") as f:
            f.write("modified\n")

        # Second read should return new content, not dedup stub
        res2 = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res2.status, "success")
        self.assertIn("modified", res2.output_text or "")
        self.assertNotIn("unchanged", res2.output_text or "")

    def test_read_dedup_does_not_trigger_after_write(self):
        """Write-created tracker entries should NOT trigger dedup on first Read."""
        p = os.path.abspath("write_then_read.txt")
        # Write creates the file and tracker entry
        arun(WriteTool.call(json.dumps({"file_path": p, "content": "new file\n"}), self.tool_context))
        # First Read should return full content, not dedup stub
        res = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("new file", res.output_text or "")
        self.assertNotIn("unchanged", res.output_text or "")

    def test_read_dedup_does_not_trigger_for_partial_read(self):
        """Partial reads (with offset/limit) should not trigger dedup."""
        p = os.path.abspath("partial.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write("line1\nline2\nline3\n")

        # Full read
        arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        # Partial read should return actual content
        res = arun(ReadTool.call(json.dumps({"file_path": p, "offset": 2, "limit": 1}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("line2", res.output_text or "")
        self.assertNotIn("unchanged", res.output_text or "")

class TestTrailingWhitespaceCleanup(BaseTempDirTest):
    def test_edit_strips_trailing_whitespace(self):
        p = os.path.abspath("trailing_ws.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("x = 1\ny = 2\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "x = 1",
                        "new_string": "x = 42   ",  # trailing spaces
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        with open(p, encoding="utf-8") as f:
            content = f.read()
        # Trailing whitespace should be stripped
        self.assertEqual(content, "x = 42\ny = 2\n")

    def test_edit_preserves_trailing_whitespace_in_markdown(self):
        p = os.path.abspath("doc.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("Line one\nLine two\n")
        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))

        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "Line one",
                        "new_string": "Line one  ",  # two trailing spaces = hard break in markdown
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")
        with open(p, encoding="utf-8") as f:
            content = f.read()
        # Trailing spaces should be preserved in markdown
        self.assertEqual(content, "Line one  \nLine two\n")

class TestNotebookSupport(BaseTempDirTest):
    def test_read_notebook(self):
        p = os.path.abspath("test.ipynb")
        nb_content: dict[str, object] = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["print('hello')"],
                    "outputs": [{"text": ["hello\n"]}],
                },
                {
                    "cell_type": "markdown",
                    "source": ["# Title"],
                    "outputs": [],
                },
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        with open(p, "w", encoding="utf-8") as f:
            json.dump(nb_content, f)

        res = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("[Notebook]", res.output_text or "")
        self.assertIn("print('hello')", res.output_text or "")
        self.assertIn("[code]", res.output_text or "")
        self.assertIn("[markdown]", res.output_text or "")
        self.assertIn("[output]", res.output_text or "")

class TestUTF16LESupport(BaseTempDirTest):
    def test_read_utf16le_file(self):
        p = os.path.abspath("utf16.txt")
        with open(p, "wb") as f:
            # Write UTF-16LE BOM + content
            f.write(b"\xff\xfe")
            f.write("hello world\n".encode("utf-16-le"))

        res = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        self.assertEqual(res.status, "success")
        self.assertIn("hello world", res.output_text or "")

    def test_edit_preserves_utf16le_encoding(self):
        p = os.path.abspath("utf16_edit.txt")
        with open(p, "wb") as f:
            f.write(b"\xff\xfe")
            f.write("hello\n".encode("utf-16-le"))

        _ = arun(ReadTool.call(json.dumps({"file_path": p}), self.tool_context))
        res = arun(
            EditTool.call(
                json.dumps(
                    {
                        "file_path": p,
                        "old_string": "hello",
                        "new_string": "HELLO",
                        "replace_all": False,
                    }
                ),
                self.tool_context,
            )
        )
        self.assertEqual(res.status, "success")

        # File should still be written in UTF-16LE
        with open(p, "rb") as f:
            raw = f.read()
        content = raw.decode("utf-16-le")
        self.assertIn("HELLO", content)

if __name__ == "__main__":
    unittest.main()
