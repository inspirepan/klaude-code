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

from codex_mini.core.tool.shell_tool import ShellTool  # noqa: E402


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


class TestShellApplyPatch(BaseTempDirTest):
    def test_apply_patch_add_file(self):
        patch_content = "\n".join(
            [
                "*** Begin Patch",
                "*** Add File: sample.txt",
                "+hello",
                "+world",
                "*** End Patch",
            ]
        )
        payload = json.dumps({"command": ["apply_patch", patch_content], "workdir": "."})

        result = arun(ShellTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/sample.txt b/sample.txt", result.ui_extra)  # type:ignore
        self.assertIn("+hello", result.ui_extra)  # type:ignore
        self.assertTrue(Path("sample.txt").exists())
        self.assertEqual(Path("sample.txt").read_text(), "hello\nworld")

    def test_apply_patch_update_file(self):
        with open("data.txt", "w", encoding="utf-8") as f:
            f.write("old line\nkeep\n")

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
        payload = json.dumps({"command": ["apply_patch", patch_content], "workdir": "."})

        result = arun(ShellTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/data.txt b/data.txt", result.ui_extra)  # type:ignore
        self.assertIn("-old line", result.ui_extra)  # type:ignore
        self.assertIn("+new line", result.ui_extra)  # type:ignore
        self.assertEqual(Path("data.txt").read_text(), "new line\nkeep\n")

    def test_apply_patch_with_heredoc(self):
        # Test Case 4: bash -lc "apply_patch heredoc"
        heredoc_script = (
            "apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: heredoc.txt\n+from heredoc\n*** End Patch\nEOF"
        )
        payload = json.dumps({"command": ["bash", "-lc", heredoc_script], "workdir": "."})

        result = arun(ShellTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/heredoc.txt b/heredoc.txt", result.ui_extra)  # type:ignore
        self.assertTrue(Path("heredoc.txt").exists())
        self.assertEqual(Path("heredoc.txt").read_text(), "from heredoc")

    def test_apply_patch_direct_heredoc(self):
        # Test Case 2: apply_patch heredoc (direct, not via bash)
        heredoc_content = (
            "<<EOF\n*** Begin Patch\n*** Add File: direct_heredoc.txt\n+from direct heredoc\n*** End Patch\nEOF"
        )
        payload = json.dumps({"command": ["apply_patch", heredoc_content], "workdir": "."})

        result = arun(ShellTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/direct_heredoc.txt b/direct_heredoc.txt", result.ui_extra)  # type:ignore
        self.assertTrue(Path("direct_heredoc.txt").exists())
        self.assertEqual(Path("direct_heredoc.txt").read_text(), "from direct heredoc")

    def test_apply_patch_bash_direct(self):
        # Test Case 3: bash -lc "apply_patch direct"
        patch_content = "*** Begin Patch\n*** Add File: bash_direct.txt\n+from bash direct\n*** End Patch"
        bash_script = f"apply_patch '{patch_content}'"
        payload = json.dumps({"command": ["bash", "-lc", bash_script], "workdir": "."})

        result = arun(ShellTool.call(payload))

        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, "Done!")
        self.assertIsNotNone(result.ui_extra)
        self.assertIn("diff --git a/bash_direct.txt b/bash_direct.txt", result.ui_extra)  # type:ignore
        self.assertTrue(Path("bash_direct.txt").exists())
        self.assertEqual(Path("bash_direct.txt").read_text(), "from bash direct")


if __name__ == "__main__":
    unittest.main()
