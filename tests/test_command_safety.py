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

from codex_mini.core.tool.command_safety import (  # noqa: E402
    _find_unquoted_token,
    _split_bash_lc_relaxed,
    _split_script_tail,
    is_safe_command,
    strip_bash_lc,
    strip_bash_lc_argv,
)


class TestStripBashLC(unittest.TestCase):
    def test_strip_returns_inner_command(self):
        command = "bash -lc 'ls -l'"
        self.assertEqual(strip_bash_lc(command), "ls -l")

    def test_strip_preserves_inner_quotes(self):
        command = "bash -lc 'echo \"hello world\"'"
        self.assertEqual(strip_bash_lc(command), 'echo "hello world"')

    def test_strip_with_additional_tokens(self):
        command = "bash -lc 'echo hi' ignored"
        self.assertEqual(strip_bash_lc(command), "echo hi")

    def test_strip_non_bash_command(self):
        command = "ls -l"
        self.assertEqual(strip_bash_lc(command), command)

    def test_strip_invalid_command_returns_original(self):
        command = "bash -lc 'unterminated"
        self.assertEqual(strip_bash_lc(command), command)


class TestStripBashLCArgv(unittest.TestCase):
    def test_strip_basic_command(self):
        argv = ["bash", "-lc", "ls -l"]
        self.assertEqual(strip_bash_lc_argv(argv), ["ls", "-l"])

    def test_strip_python_c_with_nested_quotes(self):
        inner = (
            """uv run python -c 'import shlex; command="bash -lc 'echo "hello """
            """world"'"; print(shlex.split(command, posix=True))'"""
        )
        argv = ["bash", "-lc", inner]
        stripped = strip_bash_lc_argv(argv)
        self.assertEqual(stripped[:4], ["uv", "run", "python", "-c"])
        self.assertEqual(len(stripped), 5)
        script = stripped[4]
        self.assertTrue(script.startswith("import shlex;"))
        self.assertIn('command="bash -lc \'echo "hello world"\'"', script)
        self.assertIn("print(shlex.split(command, posix=True))", script)


class TestBashLcHelperFunctions(unittest.TestCase):
    def test_find_unquoted_token_ignores_nested(self):
        command = "uv run python -c 'echo -c inner'"
        idx = _find_unquoted_token(command, "-c")
        self.assertIsNotNone(idx)
        self.assertEqual(idx, command.index("-c"))

        only_nested = "echo '-c inside'"
        self.assertIsNone(_find_unquoted_token(only_nested, "-c"))

    def test_split_script_tail_with_additional_tokens(self):
        script, rest = _split_script_tail(" 'echo hi'  extra args")
        self.assertEqual(script, "echo hi")
        self.assertEqual(rest, ["extra", "args"])

        double_quote_tail = ' "echo \\"hello\\"" '
        script2, rest2 = _split_script_tail(double_quote_tail)
        self.assertEqual(script2, 'echo \\"hello\\"')
        self.assertEqual(rest2, [])

    def test_split_bash_lc_relaxed_handles_nested_quotes(self):
        inner = (
            "uv run python -c 'import shlex; command=\"bash -lc \\'echo \"hello "
            "world\\\"\\'\"; print(shlex.split(command, posix=True))'"
        )
        parsed = _split_bash_lc_relaxed(inner)
        self.assertIsNotNone(parsed)
        assert parsed is not None  # to satisfy type checkers
        self.assertEqual(parsed[:4], ["uv", "run", "python", "-c"])
        self.assertEqual(len(parsed), 5)
        self.assertIn('command="bash -lc', parsed[4])
        self.assertIn("hello world", parsed[4])


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
    def assert_safe(self, command: str):  # noqa: N802
        result = is_safe_command(command)
        self.assertTrue(
            result.is_safe,
            msg=f"Expected SAFE, got UNSAFE for: {command} (Error: {result.error_msg})",
        )

    def assert_unsafe(self, command: str, expected_error: str | None = None):  # noqa: N802
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

    # fd
    def test_fd_safe(self):
        self.assert_safe("fd file")

    def test_fd_unsafe_exec(self):
        self.assert_unsafe("fd -x echo {}", "command execution")
        self.assert_unsafe("fd --exec echo {}", "command execution")

    # rg
    def test_rg_safe(self):
        self.assert_safe("rg hello file.txt")

    def test_rg_unsafe_flags(self):
        self.assert_unsafe("rg -z hello", "compressed file search")
        self.assert_unsafe("rg --search-zip hello", "compressed file search")
        self.assert_unsafe("rg --pre=python hello", "preprocessor command")
        self.assert_unsafe("rg --pre python", "preprocessor command")
        self.assert_unsafe("rg --hostname-bin=nc hello", "hostname command")

    # git
    def test_git_safe_locals(self):
        self.assert_safe("git status")
        self.assert_safe('git commit -m "test"')
        self.assert_safe("git diff --name-only")

    def test_git_unsafe_remotes_and_empty(self):
        self.assert_unsafe("git push", "remote operation")
        self.assert_unsafe("git", "missing subcommand")

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
            "src/codex_mini/cli/main.py"
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
            "src/codex_mini/cli/main.py && sed -n '64,80p' src/codex_mini/cli/main.py | nl"
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

    def test_blacklist_allows_unknown_commands(self):
        self.assert_safe("python --version")
        self.assert_safe("custom-tool --flag value")

    def test_cat_with_heredoc_redirection(self):
        """Ensure cat with heredoc redirection is rejected."""
        self.assert_unsafe("cat > filename <<EOF")

    def test_awk_disallowed_options(self):
        self.assert_unsafe("awk -f script.awk", "-f/--file")
        self.assert_unsafe("awk 'system(\"ls\")'", "system() call")
        self.assert_unsafe("awk 'print | \"cat\"'", "piping output")


if __name__ == "__main__":
    unittest.main()
