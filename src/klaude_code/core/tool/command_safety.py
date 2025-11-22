import os
import re
import shlex


class SafetyCheckResult:
    """Result of a safety check with detailed error information."""

    def __init__(self, is_safe: bool, error_msg: str = ""):
        self.is_safe = is_safe
        self.error_msg = error_msg


def _is_valid_sed_n_arg(s: str | None) -> bool:
    if not s:
        return False
    # Matches: Np or M,Np where M,N are positive integers
    return bool(re.fullmatch(r"\d+(,\d+)?p", s))


def _has_shell_redirection(argv: list[str]) -> bool:  # pyright: ignore
    """Detect whether argv contains shell redirection or control operators."""

    if len(argv) <= 1:
        return False

    # Heuristic detection: look for tokens that represent redirection or control operators
    redir_prefixes = ("<>", ">>", ">", "<<<", "<<-", "<<", "<&", ">&", "|")
    control_tokens = {"|", "||", "&&", ";"}

    for token in argv[1:]:
        if not token:
            continue

        if token in control_tokens:
            return True

        # Allow literal angle-bracket text such as <tag> by skipping tokens
        # that contain both '<' and '>' characters.
        if "<" in token and ">" in token:
            continue

        # Strip leading file descriptor numbers (e.g., 2>file, 1<&0)
        stripped = token.lstrip("0123456789")
        if not stripped:
            continue

        for prefix in redir_prefixes:
            if stripped.startswith(prefix):
                # Handle the pipeline-with-stderr prefix specifically
                if prefix == "|":
                    return True
                return True

    return False


def _is_safe_awk_program(program: str) -> SafetyCheckResult:
    lowered = program.lower()

    if "`" in program:
        return SafetyCheckResult(False, "awk: backticks not allowed in program")
    if "$(" in program:
        return SafetyCheckResult(False, "awk: command substitution not allowed in program")
    if "|&" in program:
        return SafetyCheckResult(False, "awk: background pipeline not allowed in program")

    if "system(" in lowered:
        return SafetyCheckResult(False, "awk: system() call not allowed in program")

    if re.search(r"(?<![|&>])\bprint\s*\|", program, re.IGNORECASE):
        return SafetyCheckResult(False, "awk: piping output to external command not allowed")
    if re.search(r"\bprintf\s*\|", program, re.IGNORECASE):
        return SafetyCheckResult(False, "awk: piping output to external command not allowed")

    return SafetyCheckResult(True)


def _is_safe_awk_argv(argv: list[str]) -> SafetyCheckResult:
    if len(argv) < 2:
        return SafetyCheckResult(False, "awk: Missing program")

    program: str | None = None

    i = 1
    while i < len(argv):
        arg = argv[i]

        if arg in {"-f", "--file", "--source"} or arg.startswith("-f"):
            return SafetyCheckResult(False, "awk: -f/--file not allowed")

        if arg in {"-e", "--exec"}:
            if i + 1 >= len(argv):
                return SafetyCheckResult(False, "awk: Missing program for -e")
            script = argv[i + 1]
            program_check = _is_safe_awk_program(script)
            if not program_check.is_safe:
                return program_check
            if program is None:
                program = script
            i += 2
            continue

        if arg.startswith("-"):
            i += 1
            continue

        if program is None:
            program_check = _is_safe_awk_program(arg)
            if not program_check.is_safe:
                return program_check
            program = arg
        i += 1

    if program is None:
        return SafetyCheckResult(False, "awk: Missing program")

    return SafetyCheckResult(True)


def _is_safe_rm_argv(argv: list[str]) -> SafetyCheckResult:
    """Check safety of rm command arguments."""
    # Enforce strict safety rules for rm operands
    # - Forbid absolute paths, tildes, wildcards (*?[), and trailing '/'
    # - Resolve each operand with realpath and ensure it stays under CWD
    # - If -r/-R/-rf/-fr present: only allow relative paths whose targets
    #   exist and are not symbolic links

    cwd = os.getcwd()
    workspace_root = os.path.realpath(cwd)

    recursive = False
    end_of_opts = False
    operands: list[str] = []

    for arg in argv[1:]:
        if not end_of_opts and arg == "--":
            end_of_opts = True
            continue

        if not end_of_opts and arg.startswith("-") and arg != "-":
            # Parse short or long options
            if arg.startswith("--"):
                # Recognize common long options
                if arg == "--recursive":
                    recursive = True
                # Other long options are ignored for safety purposes
                continue
            # Combined short options like -rf
            for ch in arg[1:]:
                if ch in ("r", "R"):
                    recursive = True
            continue

        # Operand (path)
        operands.append(arg)

    # Reject dangerous operand patterns
    wildcard_chars = {"*", "?", "["}

    for op in operands:
        # Disallow absolute paths
        if os.path.isabs(op):
            return SafetyCheckResult(False, f"rm: Absolute path not allowed: '{op}'")
        # Disallow tildes
        if op.startswith("~") or "/~/" in op or "~/" in op:
            return SafetyCheckResult(False, f"rm: Tilde expansion not allowed: '{op}'")
        # Disallow wildcards
        if any(c in op for c in wildcard_chars):
            return SafetyCheckResult(False, f"rm: Wildcards not allowed: '{op}'")
        # Disallow trailing slash (avoid whole-dir deletes)
        if op.endswith("/"):
            return SafetyCheckResult(False, f"rm: Trailing slash not allowed: '{op}'")

        # Resolve and ensure stays within workspace_root
        op_abs = os.path.realpath(os.path.join(cwd, op))
        try:
            if os.path.commonpath([op_abs, workspace_root]) != workspace_root:
                return SafetyCheckResult(False, f"rm: Path escapes workspace: '{op}' -> '{op_abs}'")
        except Exception as e:
            # Different drives or resolution errors
            return SafetyCheckResult(False, f"rm: Path resolution failed for '{op}': {e}")

        if recursive:
            # For recursive deletion, require operand exists and is not a symlink
            op_lpath = os.path.join(cwd, op)
            if not os.path.exists(op_lpath):
                return SafetyCheckResult(False, f"rm -r: Target does not exist: '{op}'")
            if os.path.islink(op_lpath):
                return SafetyCheckResult(False, f"rm -r: Cannot delete symlink recursively: '{op}'")

    # If no operands provided, allow (harmless, will fail at runtime)
    return SafetyCheckResult(True)


def _is_safe_trash_argv(argv: list[str]) -> SafetyCheckResult:
    """Check safety of trash command arguments."""
    # Apply similar safety rules as rm but slightly more permissive
    # - Forbid absolute paths, tildes, wildcards (*?[), and trailing '/'
    # - Resolve each operand with realpath and ensure it stays under CWD
    # - Unlike rm, allow symlinks since trash is less destructive

    cwd = os.getcwd()
    workspace_root = os.path.realpath(cwd)

    end_of_opts = False
    operands: list[str] = []

    for arg in argv[1:]:
        if not end_of_opts and arg == "--":
            end_of_opts = True
            continue

        if not end_of_opts and arg.startswith("-") and arg != "-":
            # Skip options for trash command
            continue

        # Operand (path)
        operands.append(arg)

    # Reject dangerous operand patterns
    wildcard_chars = {"*", "?", "["}

    for op in operands:
        # Disallow absolute paths
        if os.path.isabs(op):
            return SafetyCheckResult(False, f"trash: Absolute path not allowed: '{op}'")
        # Disallow tildes
        if op.startswith("~") or "/~/" in op or "~/" in op:
            return SafetyCheckResult(False, f"trash: Tilde expansion not allowed: '{op}'")
        # Disallow wildcards
        if any(c in op for c in wildcard_chars):
            return SafetyCheckResult(False, f"trash: Wildcards not allowed: '{op}'")
        # Disallow trailing slash (avoid whole-dir operations)
        if op.endswith("/"):
            return SafetyCheckResult(False, f"trash: Trailing slash not allowed: '{op}'")

        # Resolve and ensure stays within workspace_root
        op_abs = os.path.realpath(os.path.join(cwd, op))
        try:
            if os.path.commonpath([op_abs, workspace_root]) != workspace_root:
                return SafetyCheckResult(False, f"trash: Path escapes workspace: '{op}' -> '{op_abs}'")
        except Exception as e:
            # Different drives or resolution errors
            return SafetyCheckResult(False, f"trash: Path resolution failed for '{op}': {e}")

    # If no operands provided, allow (harmless, will fail at runtime)
    return SafetyCheckResult(True)


def _is_safe_argv(argv: list[str]) -> SafetyCheckResult:
    if not argv:
        return SafetyCheckResult(False, "Empty command")

    cmd0 = argv[0]

    # if _has_shell_redirection(argv):
    #     return SafetyCheckResult(False, "Shell redirection and pipelines are not allowed in single commands")

    # Special handling for rm to prevent dangerous operations
    if cmd0 == "rm":
        return _is_safe_rm_argv(argv)

    # Special handling for trash to prevent dangerous operations
    if cmd0 == "trash":
        return _is_safe_trash_argv(argv)

    if cmd0 == "find":
        unsafe_opts = {
            "-exec": "command execution",
            "-execdir": "command execution",
            "-ok": "interactive command execution",
            "-okdir": "interactive command execution",
            "-delete": "file deletion",
            "-fls": "file output",
            "-fprint": "file output",
            "-fprint0": "file output",
            "-fprintf": "formatted file output",
        }
        for arg in argv[1:]:
            if arg in unsafe_opts:
                return SafetyCheckResult(False, f"find: {unsafe_opts[arg]} option '{arg}' not allowed")
        return SafetyCheckResult(True)

    if cmd0 == "git":
        sub = argv[1] if len(argv) > 1 else None
        if not sub:
            return SafetyCheckResult(False, "git: Missing subcommand")

        # Allow most local git operations, but block remote operations
        allowed_git_cmds = {
            "add",
            "branch",
            "checkout",
            "commit",
            "config",
            "diff",
            "fetch",
            "init",
            "log",
            "merge",
            "mv",
            "rebase",
            "reset",
            "restore",
            "revert",
            "rm",
            "show",
            "stash",
            "status",
            "switch",
            "tag",
            "clone",
            "worktree",
        }
        # Block remote operations
        blocked_git_cmds = {"push", "pull", "remote"}

        if sub in blocked_git_cmds:
            return SafetyCheckResult(False, f"git: Remote operation '{sub}' not allowed")
        if sub not in allowed_git_cmds:
            return SafetyCheckResult(False, f"git: Subcommand '{sub}' not in allow list")
        return SafetyCheckResult(True)

    # Build tools and linters - allow all subcommands
    if cmd0 in {"cargo", "uv", "go", "ruff", "pyright", "make", "isort", "npm", "pnpm", "bun"}:
        return SafetyCheckResult(True)

    if cmd0 == "sed":
        # Allow sed -n patterns (line printing)
        if len(argv) >= 3 and argv[1] == "-n" and _is_valid_sed_n_arg(argv[2]):
            return SafetyCheckResult(True)
        # Allow simple text replacement: sed 's/old/new/g' file
        # or sed -i 's/old/new/g' file for in-place editing
        if len(argv) >= 3:
            # Find the sed script argument (usually starts with 's/')
            for arg in argv[1:]:
                if arg.startswith("s/") or arg.startswith("s|"):
                    # Basic safety check: no command execution in replacement
                    if ";" in arg:
                        return SafetyCheckResult(False, f"sed: Command separator ';' not allowed in '{arg}'")
                    if "`" in arg:
                        return SafetyCheckResult(False, f"sed: Backticks not allowed in '{arg}'")
                    if "$(" in arg:
                        return SafetyCheckResult(False, f"sed: Command substitution not allowed in '{arg}'")
                    return SafetyCheckResult(True)
        return SafetyCheckResult(
            False,
            "sed: Only text replacement (s/old/new/) or line printing (-n 'Np') is allowed",
        )

    if cmd0 == "awk":
        return _is_safe_awk_argv(argv)

    # Default allow when command is not explicitly restricted
    return SafetyCheckResult(True)


def parse_command_sequence(script: str) -> tuple[list[list[str]] | None, str]:
    """Parse command sequence separated by logical or pipe operators."""
    if not script.strip():
        return None, "Empty script"

    # Tokenize with shlex so quotes/escapes are handled by the stdlib.
    # Treat '|', '&', ';' as punctuation so they become standalone tokens.
    try:
        lexer = shlex.shlex(script, posix=True, punctuation_chars="|;&")
        tokens = list(lexer)
    except ValueError as e:
        # Preserve error format expected by callers/tests
        return None, f"Shell parsing error: {e}"

    commands: list[list[str]] = []
    cur: list[str] = []

    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]

        # Semicolon separator
        if t == ";":
            if not cur:
                return None, "Empty command in sequence"
            commands.append(cur)
            cur = []
            i += 1
            continue

        # Pipe or logical OR separators
        if t == "|" or t == "||":
            # Treat both '|' and '||' as separators between commands
            if not cur:
                return None, "Empty command in sequence"
            commands.append(cur)
            cur = []
            # If '|' and next is also '|', consume both; if already '||', consume one
            if t == "|" and i + 1 < n and tokens[i + 1] == "|":
                i += 2
            else:
                i += 1
            continue

        # Logical AND separator or background '&'
        if t == "&&" or t == "&":
            if t == "&&" or (i + 1 < n and tokens[i + 1] == "&"):
                if not cur:
                    return None, "Empty command in sequence"
                commands.append(cur)
                cur = []
                # If token is single '&' but next is '&', consume both; otherwise it's '&&' already
                if t == "&":
                    i += 2
                else:
                    i += 1
                continue
            # Single '&' becomes a normal token in argv (background op)
            cur.append(t)
            i += 1
            continue

        # Regular argument token
        cur.append(t)
        i += 1

    if not cur:
        return None, "Empty command in sequence"
    commands.append(cur)
    return commands, ""


def _find_unquoted_token(command: str, token: str) -> int | None:
    """Locate token position ensuring it appears outside quoted regions."""

    in_single = False
    in_double = False
    i = 0
    length = len(command)

    while i < length:
        ch = command[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if not in_single and not in_double and command.startswith(token, i):
            before_ok = i == 0 or command[i - 1].isspace()
            after_idx = i + len(token)
            after_ok = after_idx >= length or command[after_idx].isspace()
            if before_ok and after_ok:
                return i
        i += 1

    return None


def _split_script_tail(tail: str) -> tuple[str | None, list[str]]:
    """Split the -c tail into script and remaining tokens."""

    tail = tail.lstrip()
    if not tail:
        return None, []

    if tail[0] in {'"', "'"}:
        quote = tail[0]
        escaped = False
        in_single = False
        in_double = False
        i = 1
        while i < len(tail):
            ch = tail[i]
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == "'" and quote == '"':
                in_single = not in_single
                i += 1
                continue
            if ch == '"' and quote == "'":
                in_double = not in_double
                i += 1
                continue
            if ch == quote and not in_single and not in_double:
                script = tail[1:i]
                rest = tail[i + 1 :].lstrip()
                break
            i += 1
        else:
            # Unterminated quote: treat the remainder as script
            return tail[1:], []
    else:
        match = re.search(r"\s", tail)
        if match:
            script = tail[: match.start()]
            rest = tail[match.end() :].lstrip()
        else:
            return tail, []

    if not rest:
        return script, []

    try:
        rest_tokens = shlex.split(rest, posix=True)
    except ValueError:
        rest_tokens = rest.split()

    return script, rest_tokens


def _split_bash_lc_relaxed(command: str) -> list[str] | None:
    """Attempt relaxed parsing for bash -lc commands with inline scripts."""

    idx = _find_unquoted_token(command, "-c")
    if idx is None:
        return None

    head = command[:idx].strip()
    try:
        head_tokens = shlex.split(head, posix=True) if head else []
    except ValueError:
        return None

    flag = "-c"
    tail = command[idx + len(flag) :]
    script, rest_tokens = _split_script_tail(tail)

    result: list[str] = head_tokens + [flag]
    if script is not None:
        result.append(script)
    result.extend(rest_tokens)
    return result


def strip_bash_lc_argv(argv: list[str]) -> list[str]:
    """Extract the actual command from bash -lc format if present in argv list."""
    if len(argv) >= 3 and argv[0] == "bash" and argv[1] == "-lc":
        command = argv[2]
        try:
            parsed = shlex.split(command, posix=True)
        except ValueError:
            relaxed = _split_bash_lc_relaxed(command)
            if relaxed:
                return relaxed
            # If parsing fails, return the original command string as single item
            return [command]
        if "-c" in parsed:
            idx = parsed.index("-c")
            if len(parsed) > idx + 2:
                relaxed = _split_bash_lc_relaxed(command)
                if relaxed:
                    return relaxed
        return parsed

    # If not bash -lc format, return original argv
    return argv


def strip_bash_lc(command: str) -> str:
    """Extract the actual command from bash -lc format if present."""
    try:
        # Parse the command into tokens
        argv = shlex.split(command, posix=True)

        # Check if it's a bash -lc command
        if len(argv) >= 3 and argv[0] == "bash" and argv[1] == "-lc":
            # Return the actual command (third argument)
            return argv[2]

        # If not bash -lc format, return original command
        return command
    except ValueError:
        # If parsing fails, return original command
        return command


def is_safe_command(command: str) -> SafetyCheckResult:
    """Conservatively determine if a command is known-safe."""
    # First, try direct exec-style argv safety (e.g., "ls -l").
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        argv = []
        # Don't return error here, try sequence parsing below

    if argv:
        result = _is_safe_argv(argv)
        if result.is_safe:
            return result
        fallback_needed = result.error_msg == "Shell redirection and pipelines are not allowed in single commands"
        if not fallback_needed:
            fallback_needed = any(op in command for op in ("&&", "||", ";"))
        if not fallback_needed:
            return result

    # seq, parse_error = parse_command_sequence(command)
    # if seq:
    #     for cmd in seq:
    #         result = _is_safe_argv(cmd)
    #         if not result.is_safe:
    #             return result
    #     return SafetyCheckResult(True)

    # # If we got here, command failed both checks
    # if parse_error:
    #     return SafetyCheckResult(False, f"Script contains {parse_error}")

    if argv and not argv[0]:
        return SafetyCheckResult(False, "Empty command")
    if argv:
        # We have argv but it failed safety check earlier
        return _is_safe_argv(argv)
    return SafetyCheckResult(False, "Failed to parse command")
