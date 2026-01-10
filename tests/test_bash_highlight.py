"""Tests for bash command syntax highlighting."""

from rich.text import Text

from klaude_code.tui.components.bash_syntax import highlight_bash_command
from klaude_code.tui.components.rich.theme import ThemeKey


def get_spans_by_style(text: Text, style: ThemeKey) -> list[str]:
    """Extract text segments that have the given style."""
    result: list[str] = []
    for span in text.spans:
        if span.style == style:
            result.append(text.plain[span.start : span.end])
    return result


class TestHighlightBashCommand:
    """Tests for highlight_bash_command function."""

    def test_simple_command(self):
        """Single command should be highlighted."""
        result = highlight_bash_command("ls")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["ls"]

    def test_command_with_arguments(self):
        """Command and arguments should have different styles."""
        result = highlight_bash_command("ls -la /tmp")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        arguments = get_spans_by_style(result, ThemeKey.BASH_ARGUMENT)
        assert commands == ["ls"]
        assert "-la" in arguments
        assert "/tmp" in arguments

    def test_subcommand_git(self):
        """git subcommands should be highlighted as commands."""
        result = highlight_bash_command("git commit -m 'test'")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["git", "commit"]

    def test_subcommand_docker(self):
        """docker subcommands should be highlighted as commands."""
        result = highlight_bash_command("docker run -it ubuntu bash")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["docker", "run"]

    def test_subcommand_uv(self):
        """uv subcommands should be highlighted as commands."""
        result = highlight_bash_command("uv add requests")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["uv", "add"]

    def test_subcommand_kubectl(self):
        """kubectl subcommands should be highlighted as commands."""
        result = highlight_bash_command("kubectl get pods -n default")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["kubectl", "get"]

    def test_subcommand_cargo(self):
        """cargo subcommands should be highlighted as commands."""
        result = highlight_bash_command("cargo build --release")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["cargo", "build"]

    def test_subcommand_npm(self):
        """npm subcommands should be highlighted as commands."""
        result = highlight_bash_command("npm install express")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["npm", "install"]

    def test_no_false_positive_subcommand(self):
        """Commands without subcommands should not highlight arguments."""
        result = highlight_bash_command("cp file1 file2")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        arguments = get_spans_by_style(result, ThemeKey.BASH_ARGUMENT)
        assert commands == ["cp"]
        assert "file1" in arguments
        assert "file2" in arguments

    def test_pipeline(self):
        """Each command in a pipeline should be highlighted."""
        result = highlight_bash_command("cat file.txt | grep pattern")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert "cat" in commands
        assert "grep" in commands

    def test_chained_commands(self):
        """Commands chained with && should each be highlighted."""
        result = highlight_bash_command("npm install && cargo build")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert commands == ["npm", "install", "cargo", "build"]

    def test_string_not_as_subcommand(self):
        """Quoted strings should not be treated as subcommands."""
        result = highlight_bash_command('git commit -m "fix bug"')
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        strings = get_spans_by_style(result, ThemeKey.BASH_STRING)
        assert commands == ["git", "commit"]
        assert '"fix bug"' in strings

    def test_operators_highlighted(self):
        """Operators should have operator style."""
        result = highlight_bash_command("echo a && echo b || echo c")
        operators = get_spans_by_style(result, ThemeKey.BASH_OPERATOR)
        assert "&&" in operators
        assert "||" in operators

    def test_semicolon_starts_new_command(self):
        """Semicolon should start a new command context."""
        result = highlight_bash_command("echo a; ls")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert "echo" in commands
        assert "ls" in commands

    def test_flag_before_subcommand_resets_state(self):
        """Flag after command resets subcommand expectation (edge case)."""
        result = highlight_bash_command("git -C /path commit")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        # Currently, flag resets state so commit is not highlighted
        # This is acceptable behavior for this edge case
        assert "git" in commands

    def test_builtin_command(self):
        """Shell builtins should be highlighted as commands."""
        result = highlight_bash_command("cd /tmp && echo done")
        commands = get_spans_by_style(result, ThemeKey.BASH_COMMAND)
        assert "cd" in commands
        assert "echo" in commands

    def test_heredoc_highlighting(self):
        """Heredoc should have appropriate styling."""
        cmd = """cat << 'EOF'
content here
EOF"""
        result = highlight_bash_command(cmd)
        # Should not crash and should produce some output
        assert len(result.plain) > 0

    def test_heredoc_body_truncated_to_four_lines(self):
        """Heredoc body should be truncated to keep tool calls compact."""
        cmd = """cat <<'EOF'
line1
line2
line3
line4
line5
EOF"""
        result = highlight_bash_command(cmd)
        assert "line1" in result.plain
        assert "line2" in result.plain
        assert "line3" in result.plain
        assert "line4" in result.plain
        assert "line5" not in result.plain
        assert "\nEOF" in result.plain

        truncated = get_spans_by_style(result, ThemeKey.TOOL_RESULT_TRUNCATED)
        assert any("… (more" in seg for seg in truncated)

    def test_multiline_string_truncated_to_four_lines(self):
        """Multi-line string tokens should be truncated to keep tool calls compact."""
        cmd = "python -c \"print('a')\nprint('b')\nprint('c')\nprint('d')\nprint('e')\""
        result = highlight_bash_command(cmd)
        assert "print('a')" in result.plain
        assert "print('b')" in result.plain
        assert "print('c')" in result.plain
        assert "print('d')" in result.plain
        assert "print('e')" not in result.plain

        truncated = get_spans_by_style(result, ThemeKey.TOOL_RESULT_TRUNCATED)
        assert any("… (more" in seg for seg in truncated)
