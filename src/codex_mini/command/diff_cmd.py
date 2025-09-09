import subprocess
from pathlib import Path
from typing import Any

from codex_mini.command.command_abc import CommandABC
from codex_mini.protocol.events import DeveloperMessageEvent, Event, ToolResultEvent
from codex_mini.protocol.model import DeveloperMessageItem


class DiffCommand(CommandABC):
    """Show git diff for the current repository."""

    @property
    def name(self) -> str:
        return "diff"

    @property
    def summary(self) -> str:
        return "show git diff (including untracked files)"

    async def run(self, raw: str, session_id: str | None) -> tuple[dict[str, Any] | None, list[Event]]:
        try:
            # Run git diff in current directory
            result = subprocess.run(["git", "diff"], cwd=Path.cwd(), capture_output=True, text=True, timeout=10.0)

            if result.returncode != 0:
                # Git command failed (maybe not a git repo)
                error_msg = result.stderr.strip() or "git diff command failed"
                event = DeveloperMessageEvent(
                    session_id=session_id or "default", item=DeveloperMessageItem(content=f"Error: {error_msg}")
                )
                return None, [event]

            diff_output = result.stdout.strip()

            if not diff_output:
                # No changes
                event = DeveloperMessageEvent(
                    session_id=session_id or "default", item=DeveloperMessageItem(content="No changes")
                )
                return None, [event]

            # Has changes - create ToolResultEvent to leverage existing diff rendering
            event = ToolResultEvent(
                session_id=session_id or "default",
                response_id=None,
                tool_call_id="slash-diff",
                tool_name="bash",
                result=diff_output,
                status="success",
            )
            return None, [event]

        except subprocess.TimeoutExpired:
            event = DeveloperMessageEvent(
                session_id=session_id or "default", item=DeveloperMessageItem(content="Error: git diff command timeout")
            )
            return None, [event]
        except FileNotFoundError:
            event = DeveloperMessageEvent(
                session_id=session_id or "default", item=DeveloperMessageItem(content="Error: git command not found")
            )
            return None, [event]
        except Exception as e:
            event = DeveloperMessageEvent(
                session_id=session_id or "default", item=DeveloperMessageItem(content=f"Error：{e}")
            )
            return None, [event]
