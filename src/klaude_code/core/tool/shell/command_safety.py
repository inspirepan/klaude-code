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
    if cmd0 in {
        "cargo",
        "uv",
        "go",
        "ruff",
        "pyright",
        "make",
        "npm",
        "pnpm",
        "bun",
    }:
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


def is_safe_command(command: str) -> SafetyCheckResult:
    """Determine if a command is safe enough to run.

    The check is intentionally lightweight: it blocks only a small set of
    obviously dangerous patterns (rm/trash/git remotes, unsafe sed/awk,
    find -exec/-delete, etc.) and otherwise lets the real shell surface
    syntax errors (for example, unmatched quotes in complex multiline
    scripts).
    """

    # Try to parse into an argv-style list first. If this fails (e.g. due
    # to unterminated quotes in a complex heredoc), treat the command as
    # safe here and let bash itself perform syntax checking instead of
    # blocking execution pre-emptively.
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        # If we cannot reliably parse the command (e.g. due to unterminated
        # quotes in a complex heredoc), treat it as safe here and let the
        # real shell surface any syntax errors instead of blocking execution
        # pre-emptively.
        return SafetyCheckResult(True)

    # All further safety checks are done directly on the parsed argv via
    # _is_safe_argv. We intentionally avoid trying to re-interpret complex
    # shell sequences here and rely on the real shell to handle syntax.

    if not argv:
        return SafetyCheckResult(False, "Empty command")

    return _is_safe_argv(argv)
