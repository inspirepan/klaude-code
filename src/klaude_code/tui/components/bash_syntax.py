"""Bash command syntax highlighting for terminal display."""

import functools
import re
import shlex
from typing import Any

from pygments.lexers.shell import BashLexer  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from pygments.token import Token
from rich.text import Text

from klaude_code.const import BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES
from klaude_code.tui.components.common import shorten_path, truncate_head
from klaude_code.tui.components.rich.theme import ThemeKey

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

_SUMMARY_OPERATORS = frozenset({"&&", "||", ";", "|"})
_SUMMARY_REDIRECT_OPERATORS = frozenset({"<", "<<", "<<<", ">", ">>", "<>", "<&", ">&"})
_SUMMARY_PIPE_HELPERS = frozenset({"awk", "column", "cut", "head", "sed", "sort", "tail", "tr", "uniq", "wc"})
_SUMMARY_IGNORED_COMMANDS = frozenset({"cd"})
_SUMMARY_COMPOUND_NOISE = frozenset({"done", "echo", "fi", "true", "while"})
_SUMMARY_CONTROL_PREFIXES = frozenset({"do", "then"})
_SUMMARY_FLAGS_WITH_VALUES = frozenset(
    {
        "-A",
        "-B",
        "-C",
        "-e",
        "-f",
        "-g",
        "-m",
        "-t",
        "--after-context",
        "--before-context",
        "--context",
        "--glob",
        "--iglob",
        "--max-count",
        "--max-depth",
        "--type",
    }
)
_SUMMARY_FD_MARKER = "__klaude_fd_"

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

        # Body content (truncate to keep tool call rendering compact)
        body_inner = body.strip("\n")
        result.append("\n")
        if body_inner:
            body_text = truncate_head(
                body_inner,
                max_lines=BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES,
                base_style=ThemeKey.BASH_STRING,
                truncated_style=ThemeKey.TOOL_RESULT_TRUNCATED,
            )
            result.append_text(body_text)
            result.append("\n")

        # End delimiter
        result.append(end_delimiter, style=ThemeKey.BASH_HEREDOC_DELIMITER)
    else:
        # Fallback: couldn't parse heredoc structure
        if "\n" in token_value and len(token_value.splitlines()) > BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES:
            truncated = truncate_head(
                token_value,
                max_lines=BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES,
                base_style=ThemeKey.BASH_STRING,
                truncated_style=ThemeKey.TOOL_RESULT_TRUNCATED,
            )
            result.append_text(truncated)
        else:
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
                if "\n" in token_value and len(token_value.splitlines()) > BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES:
                    truncated = truncate_head(
                        token_value,
                        max_lines=BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES,
                        base_style=ThemeKey.BASH_STRING,
                        truncated_style=ThemeKey.TOOL_RESULT_TRUNCATED,
                    )
                    result.append_text(truncated)
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
            # Newline starts a new command context (like ; or &&)
            if "\n" in token_value:
                expect_command = True
                expect_subcommand = False
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


@functools.lru_cache(maxsize=512)
def summarize_bash_command(command: str) -> str:
    """Return a conservative one-line summary of a shell command.

    Cached: the status bar re-summarizes the same command on every spinner
    refresh, and shlex parsing is the hot path. Output only depends on the
    command string and the process cwd/home, both stable for the process.
    """

    command = _strip_heredoc_bodies(command)
    source = " ".join(command.replace("\\\n", " ").split())
    parse_source = command.replace("\\\n", " ").replace("\n", " ; ")
    if not source:
        return ""
    if _has_unquoted_shell_expansion(source):
        return source

    try:
        lexer = shlex.shlex(_protect_fd_redirects(parse_source), posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return source

    commands: list[tuple[list[str], bool, list[str]]] = []
    current: list[str] = []
    output_redirects: list[str] = []
    pipeline_stage = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _SUMMARY_OPERATORS:
            if current:
                commands.append((current, pipeline_stage, output_redirects))
                current = []
                output_redirects = []
            pipeline_stage = token == "|"
            index += 1
            continue
        if token in _SUMMARY_REDIRECT_OPERATORS:
            if current and current[-1].startswith(_SUMMARY_FD_MARKER):
                current.pop()
            if index + 1 >= len(tokens):
                return source
            target = tokens[index + 1]
            if token in {">", ">>", "<>"} and target not in {"/dev/null", "/dev/stderr", "/dev/stdout"}:
                output_redirects.append(target)
            index += 2
            continue
        if token and all(char in ";&|<>" for char in token):
            return source
        current.append(token)
        index += 1
    if current:
        commands.append((current, pipeline_stage, output_redirects))
    if not commands:
        return source

    summaries: list[str] = []
    for argv, is_pipeline_stage, redirects in commands:
        command_name = argv[0].rsplit("/", 1)[-1]
        if len(commands) > 1:
            if command_name in _SUMMARY_CONTROL_PREFIXES:
                argv = argv[1:]
                if not argv:
                    continue
                command_name = argv[0].rsplit("/", 1)[-1]
            if command_name in _SUMMARY_COMPOUND_NOISE and not redirects:
                continue
        summary = _summarize_argv(argv, pipeline_stage=is_pipeline_stage and not redirects)
        if not summary:
            continue
        if redirects:
            summary = f"{summary} → {' '.join(_shorten_paths(redirects[:1]))}"
        if summaries and summary == summaries[-1]:
            continue
        summaries.append(summary)
    if not summaries:
        return source
    if len(summaries) > 2:
        return f"{summaries[0]} · {summaries[1]} · …"
    return " · ".join(summaries)


def _has_unquoted_shell_expansion(source: str) -> bool:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            index += 1
            continue
        if quote != "'" and (char == "`" or source.startswith("$(", index)):
            return True
        if quote is None and (source.startswith("<(", index) or source.startswith(">(", index)):
            return True
        index += 1
    return False


def _protect_fd_redirects(source: str) -> str:
    result: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(source):
        char = source[index]
        if escaped:
            result.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            result.append(char)
            escaped = True
            index += 1
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            result.append(char)
            index += 1
            continue
        if quote is None and char.isdigit() and (index == 0 or source[index - 1].isspace()):
            end = index + 1
            while end < len(source) and source[end].isdigit():
                end += 1
            if end < len(source) and source[end] in "<>":
                result.append(f"{_SUMMARY_FD_MARKER}{source[index:end]}__")
                index = end
                continue
        result.append(char)
        index += 1
    return "".join(result)


def _strip_heredoc_bodies(command: str) -> str:
    lines = command.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        heredoc = _find_heredoc_declaration(line)
        if heredoc is None:
            result.append(line)
            index += 1
            continue

        start, end, delimiter, strip_tabs = heredoc
        body_end = index + 1
        while body_end < len(lines):
            candidate = lines[body_end].lstrip("\t") if strip_tabs else lines[body_end]
            if candidate == delimiter:
                break
            body_end += 1
        if body_end == len(lines):
            return command
        result.append(line[:start] + line[end:])
        index = body_end + 1
    return "\n".join(result)


def _find_heredoc_declaration(line: str) -> tuple[int, int, str, bool] | None:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            index += 1
            continue
        if quote is not None or not line.startswith("<<", index) or line.startswith("<<<", index):
            index += 1
            continue

        end = index + 2
        strip_tabs = end < len(line) and line[end] == "-"
        if strip_tabs:
            end += 1
        while end < len(line) and line[end].isspace():
            end += 1
        if end == len(line):
            return None

        delimiter_quote = line[end] if line[end] in {"'", '"'} else None
        if delimiter_quote is not None:
            delimiter_end = line.find(delimiter_quote, end + 1)
            if delimiter_end == -1:
                return None
            delimiter = line[end + 1 : delimiter_end]
            end = delimiter_end + 1
        else:
            delimiter_end = end
            while (
                delimiter_end < len(line) and not line[delimiter_end].isspace() and line[delimiter_end] not in ";&|<>"
            ):
                delimiter_end += 1
            delimiter = line[end:delimiter_end]
            end = delimiter_end
        return (index, end, delimiter, strip_tabs) if delimiter else None
    return None


def _summarize_argv(argv: list[str], *, pipeline_stage: bool) -> str | None:
    words = list(argv)
    while words and "=" in words[0] and not words[0].startswith("="):
        words.pop(0)
    if not words:
        return None

    command = words[0].rsplit("/", 1)[-1]
    if command in _SUMMARY_IGNORED_COMMANDS:
        return None
    if pipeline_stage and command in _SUMMARY_PIPE_HELPERS:
        return None

    flag_values = _SUMMARY_FLAGS_WITH_VALUES
    if command in {"rg", "rga"}:
        flag_values = flag_values | {"-r", "--replace"}
    positionals = _positional_args(words[1:], flag_values=flag_values)
    if command in {"rg", "rga", "grep"}:
        paths = _shorten_paths(positionals if "--files" in words else positionals[1:])
        return " ".join([command, *paths[:2]])
    if command == "find":
        return " ".join([command, *_shorten_paths(positionals[:1])])
    if command in {"fd", "fdfind"}:
        paths = _shorten_paths(positionals[1:] if len(positionals) > 1 else [])
        return " ".join([command, *paths[:1]])
    if command in {"git", "jj", "hg", "svn"}:
        return " ".join([command, *positionals[:1]])
    if command == "uv" and positionals[:1] == ["run"]:
        nested = positionals[:2]
        paths = _shorten_paths(positionals[2:3])
        return " ".join([command, *nested, *paths])
    if command == "npx":
        nested = positionals[:1]
        paths = _shorten_paths(positionals[1:2])
        return " ".join([command, *nested, *paths])
    if command in {"pytest", "ls"}:
        return " ".join([command, *_shorten_paths(positionals[:2])])
    if command in {"bat", "batcat", "cat", "head", "less", "more", "nl", "tail"}:
        return " ".join([command, *_shorten_paths(positionals[-1:])])
    if command == "sed":
        has_script_option = any(value in {"-e", "-f", "--expression", "--file"} for value in words[1:])
        paths = positionals[-1:] if len(positionals) > 1 or (positionals and has_script_option) else []
        return " ".join([command, *_shorten_paths(paths)])
    if command == "diff":
        return " ".join([command, *_shorten_paths(positionals[:2])])
    if command == "sips":
        return " ".join([command, *_shorten_paths(positionals[-1:])])
    return command


def _positional_args(args: list[str], *, flag_values: frozenset[str] = _SUMMARY_FLAGS_WITH_VALUES) -> list[str]:
    positionals: list[str] = []
    index = 0
    options_done = False
    while index < len(args):
        value = args[index]
        if options_done:
            positionals.append(value)
        elif value == "--":
            options_done = True
        elif value in flag_values:
            index += 1
        elif value.startswith("-"):
            pass
        else:
            positionals.append(value)
        index += 1
    return positionals


def _shorten_paths(paths: list[str]) -> list[str]:
    return [shorten_path(path) for path in paths]
