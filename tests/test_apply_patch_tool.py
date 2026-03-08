import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from klaude_code.core.tool import ApplyPatchTool  # noqa: E402
from klaude_code.core.tool.context import ToolContext, build_todo_context  # noqa: E402
from klaude_code.protocol.model import DiffUIExtra  # noqa: E402
from klaude_code.session.session import Session  # noqa: E402


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def _tool_context() -> ToolContext:
    session = Session(work_dir=Path.cwd())
    return ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
        work_dir=Path.cwd(),
        file_change_summary=session.file_change_summary,
    )


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


class TestApplyPatchTool(BaseTempDirTest):
    def test_apply_patch_add_file(self) -> None:
        patch_content = "\n".join(
            [
                "*** Begin Patch",
                "*** Add File: sample.txt",
                "+hello",
                "+world",
                "*** End Patch",
            ]
        )
        payload = json.dumps({"patch": patch_content})

        result = arun(ApplyPatchTool.call(payload, _tool_context()))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output_text, "Done!")
        self.assertIsInstance(result.ui_extra, DiffUIExtra)
        assert isinstance(result.ui_extra, DiffUIExtra)
        self.assertEqual(result.ui_extra.files[0].file_path, "sample.txt")
        assert result.ui_extra.raw_unified_diff is not None
        self.assertIn("--- /dev/null", result.ui_extra.raw_unified_diff)
        self.assertIn("+++ sample.txt", result.ui_extra.raw_unified_diff)
        added_lines = [line for line in result.ui_extra.files[0].lines if line.kind == "add"]
        self.assertTrue(any("hello" in "".join(span.text for span in line.spans) for line in added_lines))
        self.assertTrue(Path("sample.txt").exists())
        self.assertEqual(Path("sample.txt").read_text(), "hello\nworld")

    def test_apply_patch_update_file(self) -> None:
        with open("data.txt", "w", encoding="utf-8") as handle:
            handle.write("old line\nkeep\n")

        patch_content = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: data.txt",
                "-old line",
                "+new line",
                " keep",
                "*** End Patch",
            ]
        )
        payload = json.dumps({"patch": patch_content})

        result = arun(ApplyPatchTool.call(payload, _tool_context()))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output_text, "Done!")
        self.assertIsInstance(result.ui_extra, DiffUIExtra)
        assert isinstance(result.ui_extra, DiffUIExtra)
        self.assertEqual(result.ui_extra.files[0].file_path, "data.txt")
        assert result.ui_extra.raw_unified_diff is not None
        self.assertIn("--- data.txt", result.ui_extra.raw_unified_diff)
        self.assertIn("+++ data.txt", result.ui_extra.raw_unified_diff)
        removed_lines = [line for line in result.ui_extra.files[0].lines if line.kind == "remove"]
        added_lines = [line for line in result.ui_extra.files[0].lines if line.kind == "add"]
        self.assertTrue(any("".join(span.text for span in line.spans) == "old line" for line in removed_lines))
        self.assertTrue(any("".join(span.text for span in line.spans) == "new line" for line in added_lines))
        self.assertEqual(Path("data.txt").read_text(), "new line\nkeep\n")

    def test_apply_patch_add_file_absolute_path(self) -> None:
        absolute_path = os.path.join(self._tmp.name, "absolute.txt")
        patch_content = "\n".join(
            [
                "*** Begin Patch",
                f"*** Add File: {absolute_path}",
                "+hello",
                "*** End Patch",
            ]
        )
        payload = json.dumps({"patch": patch_content})

        result = arun(ApplyPatchTool.call(payload, _tool_context()))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output_text, "Done!")
        self.assertTrue(Path(absolute_path).exists())
        self.assertEqual(Path(absolute_path).read_text(), "hello")

    def test_apply_patch_records_created_edited_and_diff_totals(self) -> None:
        Path("edit.txt").write_text("old\nkeep\n", encoding="utf-8")
        session = Session(work_dir=Path.cwd())
        context = ToolContext(
            file_tracker=session.file_tracker,
            todo_context=build_todo_context(session),
            session_id=session.id,
            work_dir=Path.cwd(),
            file_change_summary=session.file_change_summary,
        )

        patch_content = "\n".join(
            [
                "*** Begin Patch",
                "*** Add File: created.md",
                "+hello",
                "+world",
                "*** Update File: edit.txt",
                "-old",
                "+new",
                " keep",
                "*** End Patch",
            ]
        )

        result = arun(ApplyPatchTool.call(json.dumps({"patch": patch_content}), context))

        self.assertEqual(result.status, "success")
        self.assertEqual(session.file_change_summary.created_files, [str(Path("created.md").resolve())])
        self.assertEqual(session.file_change_summary.edited_files, [str(Path("edit.txt").resolve())])
        self.assertEqual(session.file_change_summary.diff_lines_added, 3)
        self.assertEqual(session.file_change_summary.diff_lines_removed, 1)


if __name__ == "__main__":
    unittest.main()
