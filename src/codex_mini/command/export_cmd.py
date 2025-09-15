import os
import subprocess
import sys
import tempfile

from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.command.registry import register_command
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName
from codex_mini.protocol.events import DeveloperMessageEvent
from codex_mini.protocol.model import AssistantMessageItem, CommandOutput, DeveloperMessageItem


@register_command
class ExportCommand(CommandABC):
    """Export the last assistant message markdown content to editor"""

    @property
    def name(self) -> CommandName:
        return CommandName.EXPORT

    @property
    def summary(self) -> str:
        return "export last assistant message to editor"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        # Find the last AssistantMessageItem
        last_assistant_message: AssistantMessageItem | None = None
        for item in reversed(agent.session.conversation_history):
            if isinstance(item, AssistantMessageItem):
                last_assistant_message = item
                break

        if last_assistant_message is None or not last_assistant_message.content:
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content="No assistant message found",
                            command_output=CommandOutput(command_name=self.name, is_error=True),
                        ),
                    )
                ]
            )

        # Get editor
        editor = os.environ.get("EDITOR")

        # If no EDITOR is set, prioritize TextEdit on macOS
        if not editor:
            if sys.platform == "darwin":  # macOS
                editor = "open -a TextEdit"
            else:
                # Try common editor names on other platforms
                for cmd in ["zed", "code", "nvim", "vim", "nano", "vi"]:
                    try:
                        subprocess.run(["which", cmd], check=True, capture_output=True)
                        editor = cmd
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue

        # If no editor found, try platform-specific defaults
        if not editor:
            if sys.platform == "darwin":  # macOS
                editor = "open"
            elif sys.platform == "win32":  # Windows
                editor = "notepad"
            else:  # Linux and other Unix systems
                editor = "xdg-open"

        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tmp_file:
                tmp_file.write(last_assistant_message.content)
                tmp_path = tmp_file.name

            # Open with editor
            if editor == "open -a TextEdit":
                subprocess.run(["open", "-a", "TextEdit", tmp_path], check=True)
            elif editor in ["open", "xdg-open"]:
                subprocess.run([editor, tmp_path], check=True)
            else:
                subprocess.run([editor, tmp_path], check=True)

            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"opened last assistant message in editor: {tmp_path}",
                            command_output=CommandOutput(command_name=self.name),
                        ),
                    )
                ]
            )

        except subprocess.CalledProcessError as e:
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"failed to open editor: {e}",
                            command_output=CommandOutput(command_name=self.name, is_error=True),
                        ),
                    )
                ]
            )
        except FileNotFoundError:
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"editor '{editor}' not found, please install a text editor or set $EDITOR environment variable",
                            command_output=CommandOutput(command_name=self.name, is_error=True),
                        ),
                    )
                ]
            )
        except Exception as e:
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"error opening editor: {e}",
                            command_output=CommandOutput(command_name=self.name, is_error=True),
                        ),
                    )
                ]
            )
