import re
import subprocess
from pathlib import Path
from typing import List, Optional

import yaml

from ..user_input import UserInput
from ..utils.exception import format_exception
from .query_rewrite_command import QueryRewriteCommand


class CustomCommand(QueryRewriteCommand):
    def __init__(
        self,
        name: str,
        file_path: Path,
        content: str,
        description: str = '',
        allowed_tools: Optional[List[str]] = None,
        scope_info: str = '',
    ):
        self.name = name
        self.file_path = file_path
        self.content = content
        self.description = description
        self.allowed_tools = allowed_tools or []
        self.scope_info = scope_info

    def get_name(self) -> str:
        return self.name

    def get_command_desc(self) -> str:
        base_desc = self.description or f'Custom command from {self.file_path.name}'
        if self.scope_info:
            return f'{base_desc} {self.scope_info}'
        return base_desc

    def get_query_content(self, user_input: UserInput) -> str:
        content = self.content

        # Replace $ARGUMENTS with user input
        content = content.replace('$ARGUMENTS', user_input.cleaned_input)

        # Process bash commands
        content = self._process_bash_commands(content)

        # Process file references
        content = self._process_file_references(content)

        return content

    def _process_bash_commands(self, content: str) -> str:
        """Process !`command` patterns by executing bash commands and including output"""
        bash_pattern = r'!`([^`]+)`'

        def execute_command(match):
            command = match.group(1).strip()
            try:
                result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30, cwd=Path.cwd())

                output_parts = []
                if result.stdout.strip():
                    output_parts.append(f'<stdout>\n{result.stdout.strip()}</stdout>')
                if result.stderr.strip():
                    output_parts.append(f'<stderr>\n{result.stderr.strip()}</stderr>')
                if result.returncode != 0:
                    output_parts.append(f'<exit_code>{result.returncode}</exit_code>')

                if output_parts:
                    return f'\n<bash_result command="{command}">\n' + '\n'.join(output_parts) + '\n</bash_result>\n'
                else:
                    return f'\n<bash_result command="{command}"> (no output)</bash_result>\n'

            except subprocess.TimeoutExpired:
                return f'\n<bash_result command="{command}"> (timeout after 30s)</bash_result>\n'
            except Exception as e:
                return f'\n<bash_result command="{command}"> (error: {str(e)})</bash_result>\n'

        return re.sub(bash_pattern, execute_command, content)

    def _process_file_references(self, content: str) -> str:
        """Process @file_path patterns by including file contents"""
        file_pattern = r'@([^\s]+)'

        def read_file(match):
            file_path_str = match.group(1)
            try:
                # Resolve relative to command file's directory or current working directory
                if Path(file_path_str).is_absolute():
                    file_path = Path(file_path_str)
                else:
                    # Try relative to command file directory first
                    command_dir = self.file_path.parent.parent if self.file_path.parent.name == 'commands' else Path.cwd()
                    file_path = command_dir / file_path_str
                    if not file_path.exists():
                        # Try relative to current working directory
                        file_path = Path.cwd() / file_path_str

                if file_path.exists() and file_path.is_file():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    return f'File: {file_path}\n```\n{content}\n```'
                else:
                    return f'File: {file_path_str} (not found)'

            except Exception as e:
                return f'File: {file_path_str} (error: {str(e)})'

        return re.sub(file_pattern, read_file, content)

    @classmethod
    def from_markdown_file(cls, file_path: Path, command_name: str, scope_info: str = '') -> 'CustomCommand':
        """Create a CustomCommand from a markdown file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                file_content = f.read()
        except Exception as e:
            raise ValueError(f'Failed to read command file {file_path}: {format_exception(e)}')

        # Parse YAML frontmatter
        frontmatter = {}
        content = file_content

        if file_content.startswith('---\n'):
            try:
                parts = file_content.split('\n---\n', 2)
                if len(parts) >= 2:
                    yaml_content = parts[0][4:]  # Remove leading '---\n'
                    frontmatter = yaml.safe_load(yaml_content) or {}
                    content = parts[1] if len(parts) == 2 else '\n---\n'.join(parts[1:])
            except yaml.YAMLError:
                # If YAML parsing fails, treat the whole file as content
                pass

        description = frontmatter.get('description', '')
        allowed_tools = frontmatter.get('allowed-tools', [])

        return cls(
            name=command_name,
            file_path=file_path,
            content=content.strip(),
            description=description,
            allowed_tools=allowed_tools,
            scope_info=scope_info,
        )
