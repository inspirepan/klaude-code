import os
import re
import shlex

from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_common import truncate_tool_output
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import BASH


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

    # Special handling for rm to prevent dangerous operations
    if cmd0 == "rm":
        return _is_safe_rm_argv(argv)

    # Special handling for trash to prevent dangerous operations
    if cmd0 == "trash":
        return _is_safe_trash_argv(argv)

    # simple allow list
    if cmd0 in {
        "env",
        "cat",
        "cd",
        "cp",
        "date",
        "echo",
        "false",
        "file",
        "grep",
        "head",
        "ls",
        "mkdir",
        "mv",
        "nl",
        "pwd",
        "tail",
        "touch",
        "trash",
        "tree",
        "true",
        "wc",
        "which",
    }:
        return SafetyCheckResult(True)

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

    # fd - modern find alternative, allow all options except exec
    if cmd0 == "fd":
        unsafe_opts = {
            "-x": "command execution",
            "--exec": "command execution",
            "-X": "batch command execution",
            "--exec-batch": "batch command execution",
        }
        for arg in argv[1:]:
            if arg in unsafe_opts:
                return SafetyCheckResult(False, f"fd: {unsafe_opts[arg]} option '{arg}' not allowed")
        return SafetyCheckResult(True)

    if cmd0 == "rg":
        unsafe_noarg = {
            "--search-zip": "compressed file search",
            "-z": "compressed file search",
        }
        unsafe_witharg_prefix = {
            "--pre": "preprocessor command execution",
            "--hostname-bin": "hostname command execution",
        }

        for _, arg in enumerate(argv[1:], start=1):
            if arg in unsafe_noarg:
                return SafetyCheckResult(False, f"rg: {unsafe_noarg[arg]} option '{arg}' not allowed")
            for opt, desc in unsafe_witharg_prefix.items():
                if arg == opt:
                    return SafetyCheckResult(False, f"rg: {desc} option '{opt}' not allowed")
                if arg.startswith(opt + "="):
                    return SafetyCheckResult(False, f"rg: {desc} option '{arg}' not allowed")
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
        }
        # Block remote operations
        blocked_git_cmds = {"push", "pull", "fetch", "clone", "remote"}

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
        if len(argv) == 4 and argv[1] == "-n" and _is_valid_sed_n_arg(argv[2]) and bool(argv[3]):
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

    return SafetyCheckResult(False, f"Command '{cmd0}' not in allow list")


def _contains_disallowed_shell_syntax(script: str) -> tuple[bool, str]:
    """Check for disallowed shell syntax and return error details."""
    # Disallow subshells, command substitution, and redirections.
    # Conservative: detect raw chars; may reject some safe-but-quoted cases.
    disallowed_patterns = [
        (r"\$\(", "command substitution $()"),  # Check $( before parentheses
        (r"[()]", "subshells/parentheses"),
        (r"`", "backticks for command substitution"),
        (r"[<>]", "input/output redirection"),
        (r"\|&", "pipe stdout+stderr"),
    ]
    for pat, desc in disallowed_patterns:
        if re.search(pat, script):
            return True, desc
    return False, ""


def _parse_word_only_commands_sequence(
    script: str,
) -> tuple[list[list[str]] | None, str]:
    """Parse command sequence and return error details if failed."""
    if not script:
        return None, "Empty script"

    has_disallowed, syntax_error = _contains_disallowed_shell_syntax(script)
    if has_disallowed:
        return None, syntax_error

    # Split by allowed operators: &&, ||, ;, |
    parts = re.split(r"\s*(?:\|\||&&|;|\|)\s*", script)
    commands: list[list[str]] = []
    try:
        for part in parts:
            if not part.strip():
                return None, "Empty command in sequence"
            argv = shlex.split(part, posix=True)
            if not argv:
                return None, "Empty command after parsing"
            commands.append(argv)
    except ValueError as e:
        return None, f"Shell parsing error: {e}"
    return commands, ""


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

    # Next, allow scripts that are sequences of safe commands joined by
    # allowed operators (&&, ||, ;, |) with no redirections or subshells.
    seq, parse_error = _parse_word_only_commands_sequence(command)
    if seq:
        for cmd in seq:
            result = _is_safe_argv(cmd)
            if not result.is_safe:
                return result
        return SafetyCheckResult(True)

    # If we got here, command failed both checks
    if parse_error:
        return SafetyCheckResult(False, f"Script contains {parse_error}")
    if argv and not argv[0]:
        return SafetyCheckResult(False, "Empty command")
    if argv:
        # We have argv but it failed safety check earlier
        return _is_safe_argv(argv)
    return SafetyCheckResult(False, "Failed to parse command")


@register(BASH)
class BashTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=BASH,
            type="function",
            description="""Runs a shell command and returns its output.

### Usage Notes
- When searching for text or files, prefer using `rg`, `rg --files` or `fd` respectively because `rg` and `fd` is much faster than alternatives like `grep` and `find`. (If these command is not found, then use alternatives.)

Allowed commands:
- File operations: cat/cd/cp/date/echo/false/file/grep/head/ls/mkdir/mv/nl/pwd/rm/tail/touch/trash/tree/true/wc/which
  Note: rm restrictions — only relative paths under CWD; forbid absolute paths, tildes, wildcards (*?[), and trailing '/';
        with -r/-R, targets must exist and not be symlinks.
  Note: trash restrictions — only relative paths under CWD; forbid absolute paths, tildes, wildcards (*?[), and trailing '/'.
- Text processing: sed (simple replacements and line printing)
- Version control: git (local operations only - add/branch/checkout/commit/diff/log/merge/reset/restore/revert/show/stash/status etc.)
  Note: Remote operations (push/pull/fetch/clone) are blocked
- Build tools & linters: cargo/uv/go/ruff/pyright/make (all subcommands)
- Package managers: npm/pnpm/bun (all subcommands)
- Search: find (without -exec/-delete/-f* print options), fd (without -x/--exec), rg (without --pre/--hostname-bin/--search-zip/-z)
- Command sequences: joined by &&, ||, ;, |

Disallow: redirection, subshells/parentheses, command substitution


### Committing changes with git
When the user asks you to create a new git commit, follow these steps carefully:

1. You have the capability to call multiple tools in a single response. When multiple independent pieces of information are requested, batch your tool calls together for optimal performance. ALWAYS run the following bash commands in parallel, each using the Bash tool:
  - Run a git status command to see all untracked files.
  - Run a git diff command to see both staged and unstaged changes that will be committed.
  - Run a git log command to see recent commit messages, so that you can follow this repository's commit message style.
2. Analyze all staged changes (both previously staged and newly added) and draft a commit message:
  - Summarize the nature of the changes (eg. new feature, enhancement to an existing feature, bug fix, refactoring, test, docs, etc.). Ensure the message accurately reflects the changes and their purpose (i.e. "add" means a wholly new feature, "update" means an enhancement to an existing feature, "fix" means a bug fix, etc.).
  - Check for any sensitive information that shouldn't be committed
  - Draft a concise (1-2 sentences) commit message that focuses on the "why" rather than the "what"
  - Ensure it accurately reflects the changes and their purpose
3. You have the capability to call multiple tools in a single response. When multiple independent pieces of information are requested, batch your tool calls together for optimal performance. ALWAYS run the following commands in parallel:
   - Add relevant untracked files to the staging area.
   - Create the commit with a message.
   - Run git status to make sure the commit succeeded.
4. If the commit fails due to pre-commit hook changes, retry the commit ONCE to include these automated changes. If it fails again, it usually means a pre-commit hook is preventing the commit. If the commit succeeds but you notice that files were modified by the pre-commit hook, you MUST amend your commit to include them.

Important notes:
- NEVER update the git config
- NEVER run additional commands to read or explore code, besides git bash commands
- NEVER use the TodoWrite or Task tools
- DO NOT push to the remote repository unless the user explicitly asks you to do so
- IMPORTANT: Never use git commands with the -i flag (like git rebase -i or git add -i) since they require interactive input which is not supported.
- If there are no changes to commit (i.e., no untracked files and no modifications), do not create an empty commit
- In order to ensure good formatting, ALWAYS pass the commit message via a HEREDOC, a la this example:
<example>
git commit -m "$(cat <<'EOF'
   Commit message here.
   EOF
   )"
</example>

""",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to run",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "The timeout for the command in milliseconds, default is 60000",
                        "default": 60000,
                    },
                },
                "required": ["command"],
            },
        )

    class BashArguments(BaseModel):
        command: str
        timeout_ms: int = 60000

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = BashTool.BashArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: BashArguments) -> ToolResultItem:
        # Safety check: only execute commands proven as "known safe"
        result = is_safe_command(args.command)
        if not result.is_safe:
            return ToolResultItem(
                status="error",
                output=f"Command rejected: {result.error_msg}",
            )
        # Run the command using bash -lc so shell semantics work (pipes, &&, etc.)
        # Capture stdout/stderr, respect timeout, and return a ToolMessage.
        import asyncio
        import subprocess

        cmd = ["bash", "-lc", args.command]
        timeout_sec = max(0.0, args.timeout_ms / 1000.0)

        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            rc = completed.returncode

            if rc == 0:
                output = stdout if stdout else ""
                # Include stderr if there is useful diagnostics despite success
                if stderr.strip():
                    output = (output + ("\n" if output else "")) + f"[stderr]\n{stderr}"
                output = truncate_tool_output(output)
                return ToolResultItem(
                    status="success",
                    output=output.strip(),
                )
            else:
                combined = ""
                if stdout.strip():
                    combined += f"[stdout]\n{stdout}\n"
                if stderr.strip():
                    combined += f"[stderr]\n{stderr}"
                if not combined:
                    combined = f"Command exited with code {rc}"
                combined = truncate_tool_output(combined)
                return ToolResultItem(
                    status="error",
                    output=combined.strip(),
                )

        except subprocess.TimeoutExpired:
            return ToolResultItem(
                status="error",
                output=f"Timeout after {args.timeout_ms} ms running: {args.command}",
            )
        except FileNotFoundError:
            return ToolResultItem(
                status="error",
                output="bash not found on system path",
            )
        except Exception as e:  # safeguard against unexpected failures
            return ToolResultItem(
                status="error",
                output=f"Execution error: {e}",
            )
