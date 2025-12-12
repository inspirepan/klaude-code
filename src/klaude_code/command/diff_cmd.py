import subprocess
from pathlib import Path

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model


class DiffCommand(CommandABC):
    """Show git diff for the current repository."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.DIFF

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
                event = events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content="No in a git repo",
                        command_output=model.CommandOutput(command_name=self.name, is_error=True),
                    ),
                )
                return CommandResult(events=[event])

            # Run git diff in current directory
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                timeout=10.0,
            )

            if result.returncode != 0:
                # Git command failed
                error_msg = result.stderr.strip() or "git diff command failed"
                event = events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=f"Error: {error_msg}",
                        command_output=model.CommandOutput(command_name=self.name, is_error=True),
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
                event = events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content="", command_output=model.CommandOutput(command_name=self.name)
                    ),
                )
                return CommandResult(events=[event])

            # Has changes or untracked files
            combined_output = "\n\n".join(output_parts)
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=combined_output,
                    command_output=model.CommandOutput(command_name=self.name),
                ),
            )
            return CommandResult(events=[event])

        except subprocess.TimeoutExpired:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="Error: git diff command timeout",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])
        except FileNotFoundError:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content="Error: git command not found",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])
        except Exception as e:
            event = events.DeveloperMessageEvent(
                session_id=agent.session.id,
                item=model.DeveloperMessageItem(
                    content=f"Error：{e}",
                    command_output=model.CommandOutput(command_name=self.name, is_error=True),
                ),
            )
            return CommandResult(events=[event])
