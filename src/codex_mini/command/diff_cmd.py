import subprocess
from pathlib import Path

from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem


class DiffCommand(CommandABC):
    """Show git diff for the current repository."""

    @property
    def name(self) -> CommandName:
        return CommandName.DIFF

    @property
    def summary(self) -> str:
        return "show git diff"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        try:
            # Run git diff in current directory
            result = subprocess.run(
                ["git", "diff", "HEAD"], cwd=Path.cwd(), capture_output=True, text=True, timeout=10.0
            )

            if result.returncode != 0:
                # Git command failed (maybe not a git repo)
                error_msg = result.stderr.strip() or "git diff command failed"
                event = DeveloperMessageEvent(
                    session_id=agent.session.id, item=DeveloperMessageItem(content=f"Error: {error_msg}")
                )
                return CommandResult(events=[event])

            diff_output = result.stdout.strip()

            if not diff_output:
                # No changes
                event = DeveloperMessageEvent(
                    session_id=agent.session.id, item=DeveloperMessageItem(content="No changes")
                )
                return CommandResult(events=[event])

            # Has changes - create ToolResultEvent to leverage existing diff rendering
            event = DeveloperMessageEvent(
                session_id=agent.session.id,
                item=DeveloperMessageItem(content=diff_output, command_output=CommandOutput(command_name=self.name)),
            )
            return CommandResult(events=[event])

        except subprocess.TimeoutExpired:
            event = DeveloperMessageEvent(
                session_id=agent.session.id, item=DeveloperMessageItem(content="Error: git diff command timeout")
            )
            return CommandResult(events=[event])
        except FileNotFoundError:
            event = DeveloperMessageEvent(
                session_id=agent.session.id, item=DeveloperMessageItem(content="Error: git command not found")
            )
            return CommandResult(events=[event])
        except Exception as e:
            event = DeveloperMessageEvent(session_id=agent.session.id, item=DeveloperMessageItem(content=f"Error：{e}"))
            return CommandResult(events=[event])
