import asyncio
import subprocess

from pydantic import BaseModel

from codex_mini.core.tool.command_safety import is_safe_command, strip_bash_lc
from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_common import truncate_tool_output
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import BASH


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
- Disallow: redirection, subshells/parentheses, command substitution

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
        command_str = strip_bash_lc(args.command)

        # Safety check: only execute commands proven as "known safe"
        result = is_safe_command(command_str)
        if not result.is_safe:
            return ToolResultItem(
                status="error",
                output=f"Command rejected: {result.error_msg}",
            )

        # Run the command using bash -lc so shell semantics work (pipes, &&, etc.)
        # Capture stdout/stderr, respect timeout, and return a ToolMessage.
        cmd = ["bash", "-lc", command_str]
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
                output=f"Timeout after {args.timeout_ms} ms running: {command_str}",
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
