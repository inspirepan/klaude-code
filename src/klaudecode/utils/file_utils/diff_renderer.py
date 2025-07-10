from typing import List

from rich.console import Group
from rich.table import Table
from rich.text import Text

from ...tui import ColorStyle
from ...utils.str_utils import normalize_tabs
from .diff_analyzer import DiffAnalyzer

LINE_NUMBER_WIDTH = 3


def generate_char_level_diff(old_line: str, new_line: str) -> tuple[Text, Text]:
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


class DiffRenderer:
    def __init__(self):
        self.analyzer = DiffAnalyzer()

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
                styled_old, styled_new = generate_char_level_diff(removed_line, added_line)
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
