import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codex_mini.core.tool.apply_patch_tool import ApplyPatchTool  # noqa: E402


def arun(coro):  # type:ignore
    return asyncio.run(coro)  # type:ignore


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

        result = arun(ApplyPatchTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/sample.txt b/sample.txt", result.ui_extra)  # type:ignore[arg-type]
        self.assertIn("+hello", result.ui_extra)  # type:ignore[arg-type]
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

        result = arun(ApplyPatchTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/data.txt b/data.txt", result.ui_extra)  # type:ignore[arg-type]
        self.assertIn("-old line", result.ui_extra)  # type:ignore[arg-type]
        self.assertIn("+new line", result.ui_extra)  # type:ignore[arg-type]
        self.assertEqual(Path("data.txt").read_text(), "new line\nkeep\n")


if __name__ == "__main__":
    unittest.main()
