"""Bash command syntax highlighting for terminal display."""

import re
from typing import Any

from pygments.lexers import BashLexer  # pyright: ignore[reportUnknownVariableType]
from pygments.token import Token
from rich.text import Text

from klaude_code.ui.rich.theme import ThemeKey

# Token types for bash syntax highlighting
_STRING_TOKENS = frozenset(
    {
        Token.Literal.String,
        Token.Literal.String.Double,
        Token.Literal.String.Single,
        Token.Literal.String.Backtick,
        Token.Literal.String.Escape,
        Token.Literal.String.Heredoc,
        Token.Comment,
        Token.Comment.Single,
        Token.Comment.Hashbang,
    }
)

_OPERATOR_TOKENS = frozenset(
    {
        Token.Operator,
        Token.Punctuation,
    }
)

# Operators that start a new command context (next non-whitespace token is a command)
_COMMAND_STARTERS = frozenset({"&&", "||", "|", ";", "&"})

# Commands that have subcommands (e.g., git commit, docker run)
_SUBCOMMAND_COMMANDS = frozenset(
    {
        # Version control
        "git",
        "jj",
        "hg",
        "svn",
        # Container & orchestration
        "docker",
        "docker-compose",
        "podman",
        "kubectl",
        "helm",
        # Package managers
        "npm",
        "yarn",
        "pnpm",
        "cargo",
        "uv",
        "pip",
        "poetry",
        "brew",
        "apt",
        "apt-get",
        "dnf",
        "yum",
        "pacman",
        # Cloud CLIs
        "aws",
        "gcloud",
        "az",
        # Language tools
        "go",
        "rustup",
        "python",
        "ruby",
        # Other common tools
        "gh",
        "systemctl",
        "launchctl",
        "supervisorctl",
    }
)

_LEXER: Any = BashLexer(ensurenl=False)  # pyright: ignore[reportUnknownVariableType]

# Regex to match heredoc: << [-]? [space]? ['"]? DELIMITER ['"]? [extra] \n body \n DELIMITER
# Groups: (<<-?) (space) (quote) (delimiter) (quote) (extra on first line) (body) (end delimiter)
_HEREDOC_PATTERN = re.compile(
    r"^(<<-?)(\s*)(['\"]?)(\w+)\3([^\n]*)(\n.*\n)(\4)$",
    re.DOTALL,
)


def _append_heredoc(result: Text, token_value: str) -> None:
    """Append heredoc token with delimiter highlighting."""
    match = _HEREDOC_PATTERN.match(token_value)
    if match:
        operator, space, quote, delimiter, extra, body, end_delimiter = match.groups()
        # << or <<-
        result.append(operator, style=ThemeKey.BASH_OPERATOR)
        # Optional space
        if space:
            result.append(space)
        # Opening quote
        if quote:
            result.append(quote, style=ThemeKey.BASH_HEREDOC_DELIMITER)
        # Delimiter name (e.g., EOF)
        result.append(delimiter, style=ThemeKey.BASH_HEREDOC_DELIMITER)
        # Closing quote
        if quote:
            result.append(quote, style=ThemeKey.BASH_HEREDOC_DELIMITER)
        # Extra content on first line (e.g., "> file.py")
        if extra:
            result.append(extra, style=ThemeKey.BASH_ARGUMENT)
        # Body content
        result.append(body, style=ThemeKey.BASH_STRING)
        # End delimiter
        result.append(end_delimiter, style=ThemeKey.BASH_HEREDOC_DELIMITER)
    else:
        # Fallback: couldn't parse heredoc structure
        result.append(token_value, style=ThemeKey.BASH_STRING)


def highlight_bash_command(command: str) -> Text:
    """Apply bash syntax highlighting to a command string, returning Rich Text.

    Styling:
    - Command names (first token after line start or operators): bold green
    - Subcommands (for commands like git, docker): bold green
    - Arguments: green
    - Operators (&&, ||, |, ;): dim green
    - Strings and comments: green
    """
    result = Text()
    token_type: Any
    token_value: str

    # Track whether next non-whitespace token is a command
    expect_command = True
    # Track whether next non-flag token is a subcommand
    expect_subcommand = False

    for token_type, token_value in _LEXER.get_tokens(command):
        # Determine style based on token type and context
        if token_type in _STRING_TOKENS:
            # Check if this is a heredoc (starts with <<)
            if token_value.startswith("<<"):
                _append_heredoc(result, token_value)
            else:
                result.append(token_value, style=ThemeKey.BASH_STRING)
            expect_subcommand = False
        elif token_type in _OPERATOR_TOKENS:
            result.append(token_value, style=ThemeKey.BASH_OPERATOR)
            # After command-starting operators, next token is a command
            if token_value in _COMMAND_STARTERS:
                expect_command = True
                expect_subcommand = False
        elif token_type in (Token.Text.Whitespace,):
            result.append(token_value)
        elif token_type == Token.Name.Builtin:
            # Built-in commands are always commands
            result.append(token_value, style=ThemeKey.BASH_COMMAND)
            expect_command = False
            expect_subcommand = token_value in _SUBCOMMAND_COMMANDS
        elif expect_command and token_value.strip():
            # First non-whitespace token in command context
            result.append(token_value, style=ThemeKey.BASH_COMMAND)
            expect_command = False
            expect_subcommand = token_value in _SUBCOMMAND_COMMANDS
        elif expect_subcommand and token_value.strip() and not token_value.startswith("-"):
            # Subcommand: non-flag token after a command that has subcommands
            result.append(token_value, style=ThemeKey.BASH_COMMAND)
            expect_subcommand = False
        else:
            # Regular arguments (including flags, which reset subcommand expectation)
            result.append(token_value, style=ThemeKey.BASH_ARGUMENT)
            if token_value.strip():
                expect_subcommand = False

    return result
