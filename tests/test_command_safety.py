# pyright: reportPrivateUsage=false
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure we can import from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from klaude_code.core.tool import is_safe_command  # noqa: E402


class TestCommandSafety(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

        # Prepare a small workspace
        os.makedirs("dir1", exist_ok=True)
        with open("file.txt", "w", encoding="utf-8") as f:
            f.write("hello\n")
        with open(os.path.join("dir1", "nested.txt"), "w", encoding="utf-8") as f:
            f.write("nested\n")

        # Optional: a symlink to dir1 (skip tests using it if not supported)
        self.symlink_created = False
        try:
            os.symlink("dir1", "linkdir")
            self.symlink_created = True
        except (OSError, NotImplementedError):
            self.symlink_created = False

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()

    # Helpers
    def assert_safe(self, command: str):
        result = is_safe_command(command)
        self.assertTrue(
            result.is_safe,
            msg=f"Expected SAFE, got UNSAFE for: {command} (Error: {result.error_msg})",
        )

    def assert_unsafe(self, command: str, expected_error: str | None = None):
        result = is_safe_command(command)
        self.assertFalse(result.is_safe, msg=f"Expected UNSAFE, got SAFE for: {command}")
        if expected_error:
            self.assertIn(
                expected_error.lower(),
                result.error_msg.lower(),
                msg=f"Expected error '{expected_error}' not found in: {result.error_msg}",
            )

    # Basic allowlist - all non-rm/trash commands are allowed
    def test_basic_allowlist(self):
        self.assert_safe("ls")
        self.assert_safe("echo hello")
        self.assert_safe("pwd")
        self.assert_safe("mkdir newdir")
        self.assert_safe("find . -name '*.txt'")
        self.assert_safe("git status")
        self.assert_safe("sed 's/x/y/g' file.txt")
        self.assert_safe("awk '{print $1}' file.txt")

    # rm strict policy
    def test_rm_safe_non_recursive_relative(self):
        # relative file removal allowed by policy
        self.assert_safe("rm file.txt")
        self.assert_safe("rm -- file.txt")

    def test_rm_forbidden_patterns(self):
        # absolute, tilde, wildcard, trailing slash
        self.assert_unsafe("rm /etc/passwd", "absolute path")
        self.assert_unsafe("rm ~/file.txt", "tilde")
        self.assert_unsafe("rm a* ", "wildcard")
        self.assert_unsafe("rm dir1/", "trailing slash")

    def test_rm_recursive_requires_existing_non_symlink(self):
        # existing directory is OK
        self.assert_safe("rm -rf dir1")
        # missing path -> unsafe
        self.assert_unsafe("rm -rf missing", "does not exist")
        # symlink -> unsafe (if symlink supported)
        if self.symlink_created:
            self.assert_unsafe("rm -rf linkdir", "symlink")

    # trash policy
    def test_trash_safe_relative(self):
        self.assert_safe("trash file.txt")
        self.assert_safe("trash dir1")

    def test_trash_forbidden_patterns(self):
        self.assert_unsafe("trash /etc/passwd", "absolute path")
        self.assert_unsafe("trash ~/file.txt", "tilde")
        self.assert_unsafe("trash a*", "wildcard")
        self.assert_unsafe("trash dir1/", "trailing slash")

    def test_other_commands_allowed(self):
        # Commands other than rm/trash are allowed by default
        self.assert_safe("python --version")
        self.assert_safe("custom-tool --flag value")
        self.assert_safe("echo hi && ls")
        self.assert_safe("rg hello file.txt | wc -l")

    def test_parse_error_treated_as_safe(self):
        """Commands with parse errors should not be pre-emptively blocked."""
        self.assert_safe("echo 'unterminated")


if __name__ == "__main__":
    unittest.main()
