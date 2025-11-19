import subprocess
from pathlib import Path

from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import CommandOutput, DeveloperMessageItem


@register_command
class DiffCommand(CommandABC):
    """Show git diff for the current repository."""

    @property
    def name(self) -> CommandName:
        return CommandName.DIFF

    @property
    def summary(self) -> str:
        return "Show git diff"

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        try:
            # Check if current directory is in a git repository
            git_check = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                timeout=5.0,
            )

            if git_check.returncode != 0:
                # Not in a git repository
                event = DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content="No in a git repo",
                        command_output=CommandOutput(command_name=self.name, is_error=True),
                    ),
                )
                return CommandResult(events=[event])

            # Run git diff in current directory
            result = subprocess.run(
                ["git", "diff", "HEAD"], cwd=Path.cwd(), capture_output=True, text=True, timeout=10.0
            )

            if result.returncode != 0:
                # Git command failed
                error_msg = result.stderr.strip() or "git diff command failed"
                event = DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(
                        content=f"Error: {error_msg}",
                        command_output=CommandOutput(command_name=self.name, is_error=True),
                    ),
                )
                return CommandResult(events=[event])

            diff_output = result.stdout.strip()

            # Get untracked files
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                timeout=10.0,
            )

            untracked_files = untracked_result.stdout.strip()

            # Combine diff output and untracked files
            output_parts: list[str] = []

            if diff_output:
                output_parts.append(diff_output)

            if untracked_files:
                untracked_lines = untracked_files.split("\n")
                untracked_section = "git ls-files --others --exclude-standard\n" + "\n".join(
                    f"{file}" for file in untracked_lines
                )
                output_parts.append(untracked_section)

            if not output_parts:
                # No changes and no untracked files
                event = DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=DeveloperMessageItem(content="", command_output=CommandOutput(command_name=self.name)),
                )
                return CommandResult(events=[event])

            # Has changes or untracked files
            combined_output = "\n\n".join(output_parts)
            event = DeveloperMessageEvent(
                session_id=agent.session.id,
                item=DeveloperMessageItem(
                    content=combined_output, command_output=CommandOutput(command_name=self.name)
                ),
            )
            return CommandResult(events=[event])

        except subprocess.TimeoutExpired:
            event = DeveloperMessageEvent(
                session_id=agent.session.id,
                item=DeveloperMessageItem(
                    content="Error: git diff command timeout",
                    command_output=CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])
        except FileNotFoundError:
            event = DeveloperMessageEvent(
                session_id=agent.session.id,
                item=DeveloperMessageItem(
                    content="Error: git command not found",
                    command_output=CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])
        except Exception as e:
            event = DeveloperMessageEvent(
                session_id=agent.session.id,
                item=DeveloperMessageItem(
                    content=f"Error：{e}", command_output=CommandOutput(command_name=self.name, is_error=True)
                ),
            )
            return CommandResult(events=[event])
