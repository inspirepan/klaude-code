from pathlib import Path
from typing import Dict

from prompt_toolkit.completion import Completer, Completion

from ..utils.file_utils import FileSearcher
from .input_command import _SLASH_COMMANDS, Command
from .input_mode import NORMAL_MODE_NAME


class UserInputCompleter(Completer):
    """Custom user input completer"""

    def __init__(self, input_session):
        self.commands: Dict[str, Command] = _SLASH_COMMANDS
        self.input_session = input_session

    def get_completions(self, document, _complete_event):
        text = document.text
        cursor_position = document.cursor_position

        at_match = self._find_at_file_pattern(text, cursor_position)
        if at_match:
            try:
                yield from self._get_file_completions(at_match)
            except Exception:
                pass
            return

        if self.input_session.current_input_mode.get_name() != NORMAL_MODE_NAME:
            return

        if not text.startswith('/') or cursor_position == 0:
            return

        command_part = text[1:cursor_position] if cursor_position > 1 else ''

        if ' ' not in command_part:
            for command_name, command in self.commands.items():
                if command_name.startswith(command_part):
                    yield Completion(
                        command_name,
                        start_position=-len(command_part),
                        display=f'/{command_name:15}',
                        display_meta=command.get_command_desc(),
                    )

    def _find_at_file_pattern(self, text, cursor_position):
        for i in range(cursor_position - 1, -1, -1):
            if text[i] == '@':
                file_prefix = text[i + 1 : cursor_position]
                if file_prefix.startswith('/') or any(c in file_prefix for c in ['/', '\\']):
                    return None
                return {'at_position': i, 'prefix': file_prefix, 'start_position': i + 1 - cursor_position}
            elif text[i].isspace():
                break
        return None

    def _get_file_completions(self, at_match):
        prefix = at_match['prefix']
        start_position = at_match['start_position']

        if not prefix or prefix.startswith('/') or any(c in prefix for c in ['/', '\\']):
            return

        workdir = self.input_session.workdir

        if prefix:
            prefix_path = Path(prefix)
            if prefix_path.is_absolute():
                return
            else:
                search_dir = workdir / prefix_path.parent if prefix_path.parent != Path('.') else workdir
                name_prefix = prefix_path.name
        else:
            search_dir = workdir
            name_prefix = ''

        if not search_dir.exists() or not search_dir.is_dir():
            return

        matches = []
        try:
            files = FileSearcher.search_files_fuzzy(name_prefix or '', str(search_dir))

            for file_path in files:
                try:
                    relative_path = Path(file_path).relative_to(workdir)
                    path_str = str(relative_path)
                except ValueError:
                    relative_path = Path(file_path)
                    path_str = str(file_path)

                if name_prefix:
                    path_str_lower = path_str.lower()
                    name_prefix_lower = name_prefix.lower()

                    if name_prefix_lower not in path_str_lower:
                        continue

                matches.append({'path': relative_path, 'name': relative_path.name})
        except (OSError, PermissionError):
            return

        def sort_key(match):
            path_str = str(match['path']).lower()
            name = match['name'].lower()
            prefix_lower = name_prefix.lower() if name_prefix else ''

            if not prefix_lower:
                return (0, name)

            if name.startswith(prefix_lower):
                return (0, name)

            if prefix_lower in name:
                return (1, name)

            if path_str.startswith(prefix_lower):
                return (2, path_str)

            return (3, path_str)

        matches.sort(key=sort_key)

        matches = matches[:10]

        for match in matches:
            path_str = str(match['path'])

            yield Completion(
                path_str,
                start_position=start_position,
                display=path_str,
            )
