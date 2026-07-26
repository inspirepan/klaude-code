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

from klaude_code.protocol.models import DiffUIExtra  # noqa: E402
from klaude_code.tool import ApplyPatchTool  # noqa: E402
from klaude_code.tool.core.context import TodoContext, ToolContext  # noqa: E402


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", work_dir=Path.cwd())


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


class TestApplyPatchToolMarkdown(BaseTempDirTest):
    def test_apply_patch_add_markdown_file_uses_diff_ui_extra(self) -> None:
        patch_content = "\n".join(
            [
                "*** Begin Patch",
                "*** Add File: doc.md",
                "+# Title",
                "+",
                "+Hello",
                "*** End Patch",
            ]
        )
        payload = json.dumps({"patch": patch_content})

        result = arun(ApplyPatchTool.call(payload, _tool_context()))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output_text, "Done!")
        self.assertIsInstance(result.ui_extra, DiffUIExtra)
        assert isinstance(result.ui_extra, DiffUIExtra)
        self.assertEqual(len(result.ui_extra.files), 1)
        file_diff = result.ui_extra.files[0]
        self.assertEqual(file_diff.file_path, "doc.md")
        self.assertEqual(file_diff.change_type, "add")
        self.assertEqual(file_diff.stats_add, 3)
        self.assertTrue(any("# Title" in span.text for line in file_diff.lines for span in line.spans))

        self.assertTrue(Path("doc.md").exists())
        self.assertEqual(Path("doc.md").read_text(encoding="utf-8"), "# Title\n\nHello")


if __name__ == "__main__":
    unittest.main()
