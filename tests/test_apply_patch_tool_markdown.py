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
from klaude_code.core.tool.context import TodoContext, ToolContext  # noqa: E402
from klaude_code.protocol import model  # noqa: E402


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test")


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()


class TestApplyPatchToolMarkdown(BaseTempDirTest):
    def test_apply_patch_add_markdown_file_uses_markdown_ui_extra(self) -> None:
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
        # When adding markdown, apply_patch returns a MultiUIExtra containing markdown preview.
        # It should NOT include a diff ui block for the markdown add.
        self.assertIsInstance(result.ui_extra, model.MultiUIExtra)
        assert isinstance(result.ui_extra, model.MultiUIExtra)

        md_items = [i for i in result.ui_extra.items if isinstance(i, model.MarkdownDocUIExtra)]
        self.assertEqual(len(md_items), 1)
        self.assertTrue(md_items[0].file_path.endswith("doc.md"))
        self.assertIn("# Title", md_items[0].content)

        diff_items = [i for i in result.ui_extra.items if isinstance(i, model.DiffUIExtra)]
        self.assertEqual(len(diff_items), 0)

        self.assertTrue(Path("doc.md").exists())
        self.assertEqual(Path("doc.md").read_text(encoding="utf-8"), "# Title\n\nHello")


if __name__ == "__main__":
    unittest.main()
