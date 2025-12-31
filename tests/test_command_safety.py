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
        # Test that find with -exec and -delete are rejected
        self.assert_unsafe(r"find . -exec echo {} \;")
        self.assert_unsafe("find . -delete")

    # git
    def test_git_safe_locals(self):
        self.assert_safe("git status")
        self.assert_safe('git commit -m "test"')
        self.assert_safe("git diff --name-only")

    # sed
    def test_sed_safe_patterns(self):
        self.assert_safe("sed -n 1p file.txt")
        self.assert_safe("sed -n 1,3p file.txt")
        self.assert_safe("sed 's/x/y/g' file.txt")
        self.assert_safe("sed s/x/y/g file.txt")
        self.assert_safe("sed s|x|y|g file.txt")
        self.assert_safe("sed -n 1p")

    def test_sed_unsafe_injection(self):
        self.assert_unsafe("sed 's/x/`uname`/g' file.txt")
        self.assert_unsafe("sed 's/x/$(uname)/g' file.txt")
        # Test injection attempt
        self.assert_unsafe(r"sed 's/x/y;echo injected/g' file.txt")

    def test_sed_complex_multiline_commands(self):
        """Test complex sed commands with address ranges and multiline replacements."""
        # This complex sed command uses address ranges and multiline replacements
        # It should be rejected due to unsafe patterns
        complex_sed = (
            "sed -i '' '69,74{s/ctx: typer.Context,/ctx: typer.Context,\\n"
            "    model: str | None = typer.Option(\\n"
            "        None,\\n"
            '        "--model",\\n'
            '        help="Override model config name (uses main model by default)",\\n'
            "    ),/;\n"
            "s/asyncio.run(run_interactive())/asyncio.run(run_interactive(model=model))/}' "
            "src/klaude_code/cli/main.py"
        )
        # This should be unsafe because sed -i with complex patterns is not in the allowlist
        self.assert_unsafe(complex_sed)

        # Test the follow-up command that's chained with &&
        chained_cmd = (
            "sed -i '' '69,74{s/ctx: typer.Context,/ctx: typer.Context,\\n"
            "    model: str | None = typer.Option(\\n"
            "        None,\\n"
            '        "--model",\\n'
            '        help="Override model config name (uses main model by default)",\\n'
            "    ),/;\n"
            "s/asyncio.run(run_interactive())/asyncio.run(run_interactive(model=model))/}' "
            "src/klaude_code/cli/main.py && sed -n '64,80p' src/klaude_code/cli/main.py | nl"
        )
        # This should also be unsafe
        self.assert_unsafe(chained_cmd)

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

    # sequences
    def test_sequences_safe(self):
        self.assert_safe("echo hi && ls")
        self.assert_safe("rg hello file.txt | wc -l")
        self.assert_safe("git show HEAD:foo | sed -n '1p'")
        self.assert_safe("awk 'NR>=10 && NR<=20 {print}'")
        self.assert_safe("awk -F: '{print $1}' file.txt")

    def test_sequences_with_pipes_inside_quotes(self):
        command = (
            "nl -ba Claude_4.txt | rg -n "
            '"antml|voice_note|election_info|search_instructions|citation_instructions|artifacts_info|thinking_mode" '
            "-n --no-heading"
        )
        self.assert_safe(command)

        multiline = (
            "nl -ba Claude_4.txt | rg -n "
            '"antml|voice_note|election_info|search_instructions|citation_instructions|artifacts\n'
            ' _info|thinking_mode" -n --no-heading'
        )
        self.assert_safe(multiline)

    def test_blacklist_allows_unknown_commands(self):
        self.assert_safe("python --version")
        self.assert_safe("custom-tool --flag value")

    def test_parse_error_treated_as_safe(self):
        """Commands with parse errors should not be pre-emptively blocked."""

        # Unterminated quotes trigger shlex parsing errors, but we still
        # treat them as safe here and let the real shell surface the syntax
        # error instead of blocking execution inside the safety layer.
        self.assert_safe("echo 'unterminated")

    # def test_cat_with_heredoc_redirection(self):
    #     """Ensure cat with heredoc redirection is rejected."""
    #     self.assert_unsafe("cat > filename <<EOF")

    def test_awk_disallowed_options(self):
        self.assert_unsafe("awk -f script.awk", "-f/--file")
        self.assert_unsafe("awk 'system(\"ls\")'", "system() call")
        self.assert_unsafe("awk 'print | \"cat\"'", "piping output")


if __name__ == "__main__":
    unittest.main()
