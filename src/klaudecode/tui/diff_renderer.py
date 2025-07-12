import re
from typing import List

from rich.console import Group
from rich.table import Table
from rich.text import Text

from ..utils.file_utils.path_utils import get_relative_path_for_display
from ..utils.str_utils import normalize_tabs
from . import ColorStyle

LINE_NUMBER_WIDTH = 3


class DiffAnalyzer:
    @staticmethod
    def calculate_diff_stats(diff_lines: List[str]) -> tuple[int, int]:
        additions = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
        removals = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))
        return additions, removals

    @staticmethod
    def parse_hunk_header(line: str) -> tuple[int, int]:
        match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 1, 1

    @staticmethod
    def is_single_line_change(diff_lines: List[str], start_idx: int) -> bool:
        if start_idx == 0 or start_idx >= len(diff_lines) - 2:
            return False

        prev_line = diff_lines[start_idx - 1]
        if not (prev_line.startswith(' ') or prev_line.startswith('@@')):
            return False

        current_line = diff_lines[start_idx]
        next_line = diff_lines[start_idx + 1]
        if not (current_line.startswith('-') and next_line.startswith('+')):
            return False

        if start_idx + 2 < len(diff_lines):
            after_plus = diff_lines[start_idx + 2]
            if not (after_plus.startswith(' ') or after_plus.startswith('@@') or after_plus.startswith('---') or after_plus.startswith('+++')):
                return False

        return True

    @classmethod
    def create_summary_text(cls, diff_lines: List[str], file_path: str):
        from rich.text import Text

        additions, removals = cls.calculate_diff_stats(diff_lines)

        summary_parts = []
        if additions > 0:
            summary_parts.append(f'{additions} addition{"s" if additions != 1 else ""}')
        if removals > 0:
            summary_parts.append(f'{removals} removal{"s" if removals != 1 else ""}')

        if not summary_parts:
            return None

        display_path = get_relative_path_for_display(file_path)
        summary_text = Text.assemble('Updated ', (display_path, ColorStyle.MAIN.bold), ' with ')

        for i, part in enumerate(summary_parts):
            if i > 0:
                summary_text.append(' and ')

            words = part.split(' ', 1)
            if len(words) == 2:
                number, text = words
                summary_text.append(number, style=ColorStyle.MAIN.bold)
                summary_text.append(f' {text}')
            else:
                summary_text.append(part)

        return summary_text


class DiffRenderer:
    def __init__(self):
        self.analyzer = DiffAnalyzer()

    def render_char_level_diff(self, old_line: str, new_line: str) -> tuple[Text, Text]:
        import difflib

        matcher = difflib.SequenceMatcher(None, normalize_tabs(old_line), normalize_tabs(new_line))

        old_text = Text()
        new_text = Text()

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            old_segment = old_line[i1:i2]
            new_segment = new_line[j1:j2]

            if tag == 'equal':
                old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_LINE)
                new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_LINE)
            elif tag == 'delete':
                old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_CHAR)
            elif tag == 'insert':
                new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR)
            elif tag == 'replace':
                old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_CHAR)
                new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR)

        return old_text, new_text

    def render_diff_lines(self, diff_lines: List[str], file_path: str = None, show_summary: bool = False) -> Group:
        if not diff_lines:
            return Group()

        summary_renderable = None
        if show_summary and file_path:
            summary_renderable = self.analyzer.create_summary_text(diff_lines, file_path)

        grid = self._create_diff_grid(diff_lines)

        if summary_renderable:
            return Group(summary_renderable, grid)
        else:
            return grid

    def _create_diff_grid(self, diff_lines: List[str]) -> Table:
        old_line_num = 1
        new_line_num = 1

        grid = Table.grid(padding=(0, 0))
        grid.add_column()
        grid.add_column()
        grid.add_column(overflow='fold')

        add_line_symbol = Text('+ ')
        add_line_symbol.stylize(ColorStyle.DIFF_ADDED_LINE)
        remove_line_symbol = Text('- ')
        remove_line_symbol.stylize(ColorStyle.DIFF_REMOVED_LINE)
        context_line_symbol = Text('  ')

        i = 0
        while i < len(diff_lines):
            line = diff_lines[i]

            if line.startswith('---') or line.startswith('+++'):
                i += 1
                continue
            elif line.startswith('@@'):
                old_line_num, new_line_num = self.analyzer.parse_hunk_header(line)
                i += 1
                continue
            elif line.startswith('-'):
                i, old_line_num, new_line_num = self._handle_removed_line(diff_lines, i, old_line_num, new_line_num, grid, add_line_symbol, remove_line_symbol)
            elif line.startswith('+'):
                added_line = line[1:].strip('\n\r')
                text = Text(normalize_tabs(added_line))
                text.stylize(ColorStyle.DIFF_ADDED_LINE)
                grid.add_row(Text(f'{new_line_num:{LINE_NUMBER_WIDTH}d} '), add_line_symbol, text)
                new_line_num += 1
                i += 1
            elif line.startswith(' '):
                context_line = line[1:].strip('\n\r')
                text = Text(normalize_tabs(context_line))
                text.stylize(ColorStyle.CONTEXT_LINE)
                grid.add_row(Text(f'{new_line_num:{LINE_NUMBER_WIDTH}d} '), context_line_symbol, text)
                old_line_num += 1
                new_line_num += 1
                i += 1
            elif line.startswith('\\'):
                no_newline_text = Text(line.strip())
                no_newline_text.stylize(ColorStyle.CONTEXT_LINE)
                grid.add_row('', Text('  '), no_newline_text)
                i += 1
            else:
                grid.add_row('', '', Text(line))
                i += 1

        return grid

    def _handle_removed_line(
        self, diff_lines: List[str], i: int, old_line_num: int, new_line_num: int, grid: Table, add_line_symbol: Text, remove_line_symbol: Text
    ) -> tuple[int, int, int]:
        line = diff_lines[i]
        removed_line = line[1:].strip('\n\r')

        if i + 1 < len(diff_lines) and diff_lines[i + 1].startswith('+'):
            added_line = diff_lines[i + 1][1:].strip('\n\r')

            if self.analyzer.is_single_line_change(diff_lines, i):
                styled_old, styled_new = self.render_char_level_diff(removed_line, added_line)
                grid.add_row(Text(f'{old_line_num:{LINE_NUMBER_WIDTH}d} '), remove_line_symbol, styled_old)
                grid.add_row(Text(f'{new_line_num:{LINE_NUMBER_WIDTH}d} '), add_line_symbol, styled_new)
            else:
                old_text = Text(normalize_tabs(removed_line))
                old_text.stylize(ColorStyle.DIFF_REMOVED_LINE)
                new_text = Text(normalize_tabs(added_line))
                new_text.stylize(ColorStyle.DIFF_ADDED_LINE)
                grid.add_row(Text(f'{old_line_num:{LINE_NUMBER_WIDTH}d} '), remove_line_symbol, old_text)
                grid.add_row(Text(f'{new_line_num:{LINE_NUMBER_WIDTH}d} '), add_line_symbol, new_text)

            old_line_num += 1
            new_line_num += 1
            return i + 2, old_line_num, new_line_num
        else:
            text = Text(normalize_tabs(removed_line))
            text.stylize(ColorStyle.DIFF_REMOVED_LINE)
            grid.add_row(Text(f'{old_line_num:{LINE_NUMBER_WIDTH}d} '), remove_line_symbol, text)
            old_line_num += 1
            return i + 1, old_line_num, new_line_num
