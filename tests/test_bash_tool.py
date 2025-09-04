import os
import sys
import unittest
import tempfile
from pathlib import Path


# Ensure we can import from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from codex_mini.core.tool.bash_tool import is_safe_command  # noqa: E402


class TestBashToolSafety(unittest.TestCase):
    def set_up(self) -> None:
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

    def tear_down(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()

    # Helpers
    def assert_safe(self, command: str):  # noqa: N802
        self.assertTrue(
            is_safe_command(command), msg=f"Expected SAFE, got UNSAFE for: {command}"
        )

    def assert_unsafe(self, command: str):  # noqa: N802
        self.assertFalse(
            is_safe_command(command), msg=f"Expected UNSAFE, got SAFE for: {command}"
        )

    # Basic allowlist
    def test_basic_allowlist(self):
        self.assert_safe("ls")
        self.assert_safe("echo hello")
        self.assert_safe("pwd")
        self.assert_safe("mkdir newdir")

    # find
    def test_find_safe(self):
        self.assert_safe('find . -maxdepth 1 -name "*.txt"')

    def test_find_unsafe_exec_and_delete(self):
        self.assert_unsafe("find . -exec echo {} \\;")
        self.assert_unsafe("find . -delete")

    # fd
    def test_fd_safe(self):
        self.assert_safe("fd file")

    def test_fd_unsafe_exec(self):
        self.assert_unsafe("fd -x echo {}")
        self.assert_unsafe("fd --exec echo {}")

    # rg
    def test_rg_safe(self):
        self.assert_safe("rg hello file.txt")

    def test_rg_unsafe_flags(self):
        self.assert_unsafe("rg -z hello")
        self.assert_unsafe("rg --search-zip hello")
        self.assert_unsafe("rg --pre=python hello")
        self.assert_unsafe("rg --pre python")
        self.assert_unsafe("rg --hostname-bin=nc hello")

    # git
    def test_git_safe_locals(self):
        self.assert_safe("git status")
        self.assert_safe('git commit -m "test"')
        self.assert_safe("git diff --name-only")

    def test_git_unsafe_remotes_and_empty(self):
        self.assert_unsafe("git push")
        self.assert_unsafe("git fetch")
        self.assert_unsafe("git clone . tmp")
        self.assert_unsafe("git")

    # sed
    def test_sed_safe_patterns(self):
        self.assert_safe("sed -n 1p file.txt")
        self.assert_safe("sed -n 1,3p file.txt")
        self.assert_safe("sed 's/x/y/g' file.txt")
        self.assert_safe("sed s/x/y/g file.txt")
        self.assert_safe("sed s|x|y|g file.txt")

    def test_sed_unsafe_injection(self):
        self.assert_unsafe("sed 's/x/`uname`/g' file.txt")
        self.assert_unsafe("sed 's/x/$(uname)/g' file.txt")
        self.assert_unsafe("sed 's/x/y/g; echo injected' file.txt")

    # rm strict policy
    def test_rm_safe_non_recursive_relative(self):
        # relative file removal allowed by policy
        self.assert_safe("rm file.txt")
        self.assert_safe("rm -- file.txt")

    def test_rm_forbidden_patterns(self):
        # absolute, tilde, wildcard, trailing slash
        self.assert_unsafe("rm /etc/passwd")
        self.assert_unsafe("rm ~/file.txt")
        self.assert_unsafe("rm a* ")
        self.assert_unsafe("rm dir1/")

    def test_rm_recursive_requires_existing_non_symlink(self):
        # existing directory is OK
        self.assert_safe("rm -rf dir1")
        # missing path -> unsafe
        self.assert_unsafe("rm -rf missing")
        # symlink -> unsafe (if symlink supported)
        if self.symlink_created:
            self.assert_unsafe("rm -rf linkdir")

    # sequences
    def test_sequences_safe(self):
        self.assert_safe("echo hi && ls")
        self.assert_safe("rg hello file.txt | wc -l")

    def test_sequences_disallowed_shell_syntax(self):
        # command substitution and subshells should be rejected in sequences
        self.assert_unsafe("true; (echo hi)")


if __name__ == "__main__":
    unittest.main()
