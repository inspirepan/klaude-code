from pathlib import Path
from typing import Dict, List, Optional

from ..tui import ColorStyle, console
from ..user_input import register_slash_command
from ..utils.exception import format_exception
from .custom_command import CustomCommand


class CustomCommandManager:
    def __init__(self):
        self.project_commands: Dict[str, CustomCommand] = {}
        self.user_commands: Dict[str, CustomCommand] = {}
        self.registered_commands: List[str] = []

    @classmethod
    def user_commands_dir(cls) -> Path:
        return Path.home() / '.claude' / 'commands'

    @classmethod
    def project_commands_dir(cls, workdir: Optional[Path] = None) -> Path:
        if workdir is None:
            workdir = Path.cwd()
        return workdir / '.claude' / 'commands'

    def discover_and_register_commands(self, workdir: Path = None):
        """Discover and register all custom commands"""
        if workdir is None:
            workdir = Path.cwd()

        # Clear previously registered commands
        self._unregister_all()

        # Discover project commands
        project_commands_dir = CustomCommandManager.project_commands_dir(workdir)
        if project_commands_dir.exists():
            self._discover_commands(project_commands_dir, 'project')

        # Discover user commands
        user_commands_dir = CustomCommandManager.user_commands_dir()
        if user_commands_dir.exists():
            self._discover_commands(user_commands_dir, 'user')

        # Register all discovered commands
        self._register_all()

    def _discover_commands(self, commands_dir: Path, scope: str):
        """Discover commands in a directory with namespace support"""
        try:
            for md_file in commands_dir.rglob('*.md'):
                try:
                    # Calculate command name with namespace
                    relative_path = md_file.relative_to(commands_dir)
                    path_parts = list(relative_path.parts)
                    path_parts[-1] = path_parts[-1][:-3]  # Remove .md extension

                    # Use only the final part as command name
                    if len(path_parts) == 1:
                        # No namespace: just command name
                        command_name = path_parts[0]
                        scope_info = f'({scope})'
                    else:
                        # With namespace: use only the last part as command name
                        command_name = path_parts[-1]
                        scope_info = f'({scope}:{":".join(path_parts[:-1])})'

                    # Create command instance with scope info
                    command = CustomCommand.from_markdown_file(md_file, command_name, scope_info)

                    # Store in appropriate dictionary using command name directly
                    if scope == 'project':
                        self.project_commands[command_name] = command
                    else:
                        self.user_commands[command_name] = command

                except Exception as e:
                    console.print(f'Error loading command from {md_file}: {format_exception(e)}', style=ColorStyle.ERROR)
                    continue

        except Exception as e:
            console.print(f'Error scanning commands directory {commands_dir}: {format_exception(e)}', style=ColorStyle.ERROR)

    def _register_all(self):
        """Register all discovered commands with the system following priority: system > project > user"""
        # Register user commands first (lowest priority)
        for command_name, command in self.user_commands.items():
            try:
                register_slash_command(command)
                self.registered_commands.append(command_name)
            except Exception as e:
                console.print(f'Error registering user command {command_name}: {format_exception(e)}', style=ColorStyle.ERROR)

        # Register project commands (higher priority - will override user commands)
        for command_name, command in self.project_commands.items():
            try:
                register_slash_command(command)
                if command_name not in self.registered_commands:
                    self.registered_commands.append(command_name)
            except Exception as e:
                console.print(f'Error registering project command {command_name}: {format_exception(e)}', style=ColorStyle.ERROR)

    def _unregister_all(self):
        """Unregister all previously registered custom commands"""
        # Note: The current system doesn't have an unregister mechanism
        # This is a placeholder for when we need to support command reloading
        self.registered_commands.clear()
        self.project_commands.clear()
        self.user_commands.clear()

    def get_all_commands(self) -> Dict[str, CustomCommand]:
        """Get all registered custom commands"""
        all_commands = {}
        all_commands.update(self.project_commands)
        all_commands.update(self.user_commands)
        return all_commands

    def reload_commands(self, workdir: Path = None):
        """Reload all custom commands"""
        self.discover_and_register_commands(workdir)

    def get_command_info(self) -> str:
        """Get information about all registered custom commands"""
        info_lines = []

        if self.project_commands:
            info_lines.append('Project Commands:')
            for name, cmd in self.project_commands.items():
                info_lines.append(f'  /{name} - {cmd.get_command_desc()}')

        if self.user_commands:
            info_lines.append('User Commands:')
            for name, cmd in self.user_commands.items():
                info_lines.append(f'  /{name} - {cmd.get_command_desc()}')

        if not self.project_commands and not self.user_commands:
            info_lines.append('No custom commands found.')
            info_lines.append('Create .md files in .claude/commands/ (project) or ~/.claude/commands/ (user)')

        return '\n'.join(info_lines)


# Global instance
custom_command_manager = CustomCommandManager()
