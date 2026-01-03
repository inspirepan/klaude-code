import os
import shlex


class SafetyCheckResult:
    """Result of a safety check with detailed error information."""

    def __init__(self, is_safe: bool, error_msg: str = ""):
        self.is_safe = is_safe
        self.error_msg = error_msg


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

    if cmd0 == "rm":
        return _is_safe_rm_argv(argv)

    if cmd0 == "trash":
        return _is_safe_trash_argv(argv)

    # Default allow when command is not explicitly restricted
    return SafetyCheckResult(True)


def is_safe_command(command: str) -> SafetyCheckResult:
    """Determine if a command is safe enough to run.

    Only rm and trash commands are checked for safety. All other commands
    are allowed by default.
    """
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        # If we cannot reliably parse the command, treat it as safe here
        # and let the real shell surface any syntax errors
        return SafetyCheckResult(True)

    if not argv:
        return SafetyCheckResult(False, "Empty command")

    return _is_safe_argv(argv)
