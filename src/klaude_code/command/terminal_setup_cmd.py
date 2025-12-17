import os
import subprocess
from pathlib import Path

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model


class TerminalSetupCommand(CommandABC):
    """Setup shift+enter newline functionality in terminal"""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.TERMINAL_SETUP

    @property
    def summary(self) -> str:
        return "Install shift+enter key binding for newlines"

    @property
    def is_interactive(self) -> bool:
        return False

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        term_program = os.environ.get("TERM_PROGRAM", "").lower()

        try:
            if term_program == "ghostty":
                message = self._setup_ghostty()
            elif term_program == "iterm.app":
                message = self._setup_iterm()
            elif term_program == "vscode":
                # VS Code family terminals (VS Code, Windsurf, Cursor) all report TERM_PROGRAM=vscode
                message = self._setup_vscode_family()
            else:
                # Provide generic manual configuration guide for unknown or unsupported terminals
                message = self._setup_generic(term_program)

            return self._create_success_result(agent, message)

        except Exception as e:
            return self._create_error_result(agent, f"Error configuring terminal: {e!s}")

    def _setup_ghostty(self) -> str:
        """Configure shift+enter newline for Ghostty terminal"""
        config_dir = Path.home() / ".config" / "ghostty"
        config_file = config_dir / "config"

        keybind_line = 'keybind="shift+enter=text:\\n"'

        # Ensure config directory exists
        config_dir.mkdir(parents=True, exist_ok=True)

        # Check if configuration already exists in config file
        if config_file.exists():
            content = config_file.read_text()
            if keybind_line in content or 'keybind="shift+enter=' in content:
                return "Ghostty terminal shift+enter newline configuration already exists"

        # Add configuration
        with config_file.open("a", encoding="utf-8") as f:
            if config_file.exists() and not config_file.read_text().endswith("\n"):
                f.write("\n")
            f.write(f"{keybind_line}\n")

        return f"Added shift+enter newline configuration for Ghostty terminal to {config_file}"

    def _setup_iterm(self) -> str:
        """Configure shift+enter newline for iTerm terminal using defaults command"""
        try:
            # First check if iTerm preferences exist
            prefs_path = Path.home() / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
            if not prefs_path.exists():
                return "iTerm preferences file not found. Please open iTerm first to create initial preferences."

            # Check if the key binding already exists
            check_cmd = ["defaults", "read", "com.googlecode.iterm2", "New Bookmarks"]

            try:
                result = subprocess.run(check_cmd, capture_output=True, text=True, check=True)
                # If we can read bookmarks, iTerm is properly configured
            except subprocess.CalledProcessError:
                return "Unable to read iTerm configuration. Please ensure iTerm is properly installed and has been opened at least once."

            # Add to the default profile's keyboard map
            add_keymap_cmd = [
                "defaults",
                "write",
                "com.googlecode.iterm2",
                "GlobalKeyMap",
                "-dict-add",
                # Do not include quotes when passing args as a list (no shell)
                "0x0d-0x20000",
                # Pass Property List dict directly; \n should be literal backslash-n so iTerm parses newline
                '{Action=12;Text="\\\\n";}',
            ]
            # Execute without shell so arguments are passed correctly
            result = subprocess.run(add_keymap_cmd, capture_output=True, text=True)
            print(result.stdout, result.stderr)
            if result.returncode == 0:
                return "Successfully configured Shift+Enter for newline in iTerm. Please restart iTerm for changes to take effect."
            else:
                # Fallback to manual instructions if defaults command fails
                return (
                    "Automatic configuration failed. Please manually configure:\n"
                    "1. Open iTerm -> Preferences (⌘,)\n"
                    "2. Go to Profiles -> Keys -> Key Mappings\n"
                    "3. Click '+' to add: Shift+Enter -> Send Text -> \\n"
                )

        except Exception as e:
            raise Exception(f"Error configuring iTerm: {e!s}") from e

    def _setup_vscode_family(self) -> str:
        """Configure shift+enter newline for VS Code family terminals (VS Code, Windsurf, Cursor).

        These editors share TERM_PROGRAM=vscode and use keybindings.json under their respective
        Application Support folders. We ensure the required keybinding exists; if not, we append it.
        """
        base_dir = Path.home() / "Library" / "Application Support"
        targets = [
            ("VS Code", base_dir / "Code" / "User" / "keybindings.json"),
            ("Windsurf", base_dir / "Windsurf" / "User" / "keybindings.json"),
            ("Cursor", base_dir / "Cursor" / "User" / "keybindings.json"),
        ]

        mapping_block = r"""    {
        "key": "shift+enter",
        "command": "workbench.action.terminal.sendSequence",
        "args": {
            "text": "\\\r\n"
        },
        "when": "terminalFocus"
    }"""

        results: list[str] = []

        for name, file_path in targets:
            try:
                _, msg = self._ensure_vscode_keybinding(file_path, mapping_block)
                results.append(f"{name}: {msg}")
            except Exception as e:  # pragma: no cover - protect against any unexpected FS issue
                results.append(f"{name}: failed to update keybindings ({e})")

        return "\n".join(results)

    def _ensure_vscode_keybinding(self, path: Path, mapping_block: str) -> tuple[bool, str]:
        """Ensure the VS Code-style keybinding exists in the given keybindings.json file.

        Returns (added, message).
        - added=True if we created or modified the file to include the mapping
        - added=False if mapping already present or file couldn't be safely modified
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        # If file does not exist, create with the mapping in an array
        if not path.exists():
            content = "[\n  " + mapping_block + "\n]\n"
            path.write_text(content, encoding="utf-8")
            return True, f"created {path} with Shift+Enter mapping"

        # Read existing content
        raw = path.read_text(encoding="utf-8")
        text = raw

        # Quick detection: if both key and command exist together anywhere, assume configured
        if '"key": "shift+enter"' in text and "workbench.action.terminal.sendSequence" in text:
            return False, "already configured"

        stripped = text.strip()
        # If file is empty, write a fresh array
        if stripped == "":
            content = "[\n  " + mapping_block + "\n]\n"
            path.write_text(content, encoding="utf-8")
            return True, "initialized empty keybindings.json with mapping"

        # If the content contains a top-level array (allowing header comments), append before the final ]
        open_idx = text.find("[")
        close_idx = text.rfind("]")
        if open_idx != -1 and close_idx != -1 and open_idx < close_idx:
            before = text[:close_idx].rstrip()
            after = text[close_idx:]

            # Heuristic: treat as non-empty if there's an object marker between [ and ]
            inner = text[open_idx + 1 : close_idx]
            has_item = "{" in inner

            # Construct new content by adding optional comma, newline, then our block
            new_content = before + ("," if has_item else "") + "\n" + mapping_block + "\n" + after

            path.write_text(new_content, encoding="utf-8")
            return True, "appended mapping"

        # Not an array – avoid modifying to prevent corrupting user config
        return (
            False,
            "unsupported keybindings.json format (not an array); please add mapping manually",
        )

    def _setup_generic(self, term_program: str) -> str:
        """Provide generic manual configuration guide for unknown or unsupported terminals"""
        if term_program:
            intro = f"Terminal type '{term_program}' is not specifically supported, but you can manually configure shift+enter newline functionality."
        else:
            intro = "Unable to detect terminal type, but you can manually configure shift+enter newline functionality."

        message = (
            f"{intro}\n\n"
            "General steps to configure shift+enter for newline:\n"
            "1. Open your terminal's preferences/settings\n"
            "2. Look for 'Key Bindings', 'Key Mappings', or 'Keyboard' section\n"
            "3. Add a new key binding:\n"
            "   - Key combination: Shift+Enter\n"
            "   - Action: Send text or Insert text\n"
            "   - Text to send: \\n (literal newline character)\n"
            "4. Save the configuration\n\n"
            "Note: The exact steps may vary depending on your terminal application. "
            "Currently supported terminals with automatic configuration: Ghostty, iTerm.app, VS Code family (VS Code, Windsurf, Cursor)"
        )

        return message

    def _create_success_result(self, agent: "Agent", message: str) -> CommandResult:
        """Create success result"""
        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=message,
                        command_output=model.CommandOutput(command_name=self.name, is_error=False),
                    ),
                )
            ]
        )

    def _create_error_result(self, agent: "Agent", message: str) -> CommandResult:
        """Create error result"""
        return CommandResult(
            events=[
                events.DeveloperMessageEvent(
                    session_id=agent.session.id,
                    item=model.DeveloperMessageItem(
                        content=message,
                        command_output=model.CommandOutput(command_name=self.name, is_error=True),
                    ),
                )
            ]
        )
