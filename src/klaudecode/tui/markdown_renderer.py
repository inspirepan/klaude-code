import re
from typing import List, Optional, Union

from rich import box
from rich.console import Group
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ..utils.str_utils import normalize_tabs
from .colors import ColorStyle


def _process_inline_formatting(text: str, style: str = '') -> Text:
    """Process inline markdown formatting like bold, italic, code, strikethrough using Text.assemble"""
    if not text:
        return Text()

    segments = []
    pos = 0

    # Pattern for all inline formatting with named groups - order matters for precedence
    pattern = r'(\*\*\*(?P<bold_italic>.*?)\*\*\*)|(\*\*(?P<bold>.*?)\*\*)|(__(?P<underscore_bold>.*?)__)|(_\*(?P<underscore_star_italic>[^*\n]+?)\*_)|(\*_(?P<star_underscore_italic>[^_\n]+?)_\*)|(\*(?P<italic>[^*\n]+?)\*)|(_(?P<underscore_italic>[^_\n]+?)_)|(`(?P<code>[^`\n]+?)`)|(\~\~(?P<strike>.*?)\~\~)'

    for match in re.finditer(pattern, text):
        # Add text before the match
        if match.start() > pos:
            segments.append((text[pos : match.start()]))

        # Add formatted text based on which group matched
        if match.group('bold_italic'):
            segments.append((match.group('bold_italic'), Style(bold=True, italic=True)))
        elif match.group('bold'):
            segments.append((match.group('bold'), Style(bold=True)))
        elif match.group('underscore_bold'):
            segments.append((match.group('underscore_bold'), Style(bold=True)))
        elif match.group('underscore_star_italic'):
            segments.append((match.group('underscore_star_italic'), Style(italic=True)))
        elif match.group('star_underscore_italic'):
            segments.append((match.group('star_underscore_italic'), Style(italic=True)))
        elif match.group('italic'):
            segments.append((match.group('italic'), Style(italic=True)))
        elif match.group('underscore_italic'):
            segments.append((match.group('underscore_italic'), Style(italic=True)))
        elif match.group('code'):
            segments.append((match.group('code'), ColorStyle.INLINE_CODE))
        elif match.group('strike'):
            segments.append((match.group('strike'), Style(strike=True)))

        pos = match.end()

    # Add remaining text
    if pos < len(text):
        segments.append(text[pos:])

    return Text.assemble(*segments, style=style) if segments else Text(text, style=style)


def _is_table_row(line: str) -> bool:
    """Check if line is a table row"""
    return line.strip().startswith('|') and line.strip().endswith('|')


def _is_table_separator(line: str) -> bool:
    """Check if line is a table separator (header separator)"""
    return bool(re.match(r'^\s*\|[\s\-\|:]+\|\s*$', line))


def _should_parse_as_table(lines: List[str], index: int) -> bool:
    """Check if current line should be parsed as start of table"""
    if not _is_table_row(lines[index]):
        return False

    if index + 1 < len(lines):
        next_line = lines[index + 1].strip()
        return _is_table_separator(next_line) or _is_table_row(next_line)

    return False


def _parse_markdown_table(lines: List[str], start_index: int, style: Optional[Union[str, Style]] = None) -> dict:
    """Parse markdown table and return rich Table"""
    header_line = lines[start_index].strip()

    # Extract headers and process inline formatting
    header_cells = [cell.strip() for cell in header_line.split('|')[1:-1]]
    headers = []
    for cell in header_cells:
        header_text = _process_inline_formatting(cell, style)
        headers.append(header_text)

    # Create table
    table = Table(show_header=True, header_style='bold', box=box.SQUARE, show_lines=True, style=style, border_style=ColorStyle.LINE)
    for header in headers:
        table.add_column(header)

    # Check if next line is separator
    i = start_index + 1
    if i < len(lines) and _is_table_separator(lines[i]):
        # Skip separator line
        i += 1

    # Parse data rows
    while i < len(lines) and _is_table_row(lines[i]):
        row_data = [cell.strip() for cell in lines[i].split('|')[1:-1]]
        # Pad row if it has fewer columns than headers
        while len(row_data) < len(headers):
            row_data.append('')

        # Process inline formatting for each cell
        formatted_row = []
        for cell_data in row_data[: len(headers)]:
            cell_text = _process_inline_formatting(cell_data, style)
            formatted_row.append(cell_text)

        table.add_row(*formatted_row)
        i += 1

    return {'table': table, 'end_index': i}


def _process_header_line(line: str, style: Optional[Union[str, Style]] = None, line_number: int = 0):
    """Process markdown header lines (##, ###, etc.)"""
    stripped = line.strip()
    header_match = re.match(r'^(#+)\s+(.+)', stripped)

    if not header_match:
        processed_text = _process_inline_formatting(line)
        processed_text.stylize(style + Style(bold=True) if style else Style(bold=True))
        return processed_text

    hashes, title = header_match.groups()

    if len(hashes) == 2:
        title_text = _process_inline_formatting(title, ColorStyle.HEADER_2.bold)
        if line_number == 0:
            return Group(title_text, Rule(style=ColorStyle.LINE, characters='╌'))
        else:
            return Group('', title_text, Rule(style=ColorStyle.LINE, characters='╌'))
    elif len(hashes) == 3:
        return _process_inline_formatting(title, ColorStyle.HEADER_3.bold)
    elif len(hashes) == 4:
        return _process_inline_formatting(title, ColorStyle.HIGHLIGHT)
    else:
        return _process_inline_formatting(title, 'bold')


def _process_quote_line(line: str, style: Optional[Union[str, Style]] = None):
    """Process markdown quote lines (> text)"""
    quote_content = re.sub(r'^(\s*)>\s?', r'\1', line)
    quote_text = _process_inline_formatting(f'▌ {quote_content}', ColorStyle.HINT)
    return quote_text


def _process_list_line(line: str, style: Optional[Union[str, Style]] = None):
    """Process markdown list lines (*, -, +, 1., etc.)"""
    list_match = re.match(r'^(\s*)([*\-+]|\d+\.)\s+(.+)', line)

    if not list_match:
        return None

    indent, marker, content = list_match.groups()

    # Create a grid with proper indentation
    table = Table.grid(padding=(0, 0))
    table.add_column(width=len(indent) + len(marker) + 1, no_wrap=True)
    table.add_column(overflow='fold')

    marker_text = Text(f'{indent}{marker} ')
    content_text = _process_inline_formatting(content, style)
    table.add_row(marker_text, content_text)

    return table


def _process_regular_line(line: str, style: Optional[Union[str, Style]] = None):
    """Process regular text lines"""
    if line.strip() == '---':
        return Group('', Rule(style=ColorStyle.LINE, characters='═'), '')

    # Try to process as list item first
    list_result = _process_list_line(line, style)
    if list_result is not None:
        return list_result

    # Process inline formatting and apply style
    text_obj = _process_inline_formatting(line, style)
    return text_obj


def render_markdown(text: str, style: Optional[Union[str, Style]] = None) -> Group:
    """Convert Markdown syntax to Rich Group"""
    if not text:
        return Group()

    lines = text.split('\n')
    formatted_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        line = normalize_tabs(line)

        # Check for table start
        if _should_parse_as_table(lines, i):
            table_result = _parse_markdown_table(lines, i, style=style)
            formatted_lines.append(table_result['table'])
            i = table_result['end_index']
            continue

        # Process different line types
        if line.strip().startswith('##'):
            processed_line = _process_header_line(line, style, i)

            # # Check if next line is empty and convert it to rule
            if not line.strip().startswith('###') and i + 1 < len(lines) and lines[i + 1].strip() == '':
                i += 1  # Skip both header and empty line
        elif line.strip().startswith('>'):
            processed_line = _process_quote_line(line, style)
        else:
            processed_line = _process_regular_line(line, style)
        formatted_lines.append(processed_line)

        i += 1

    return Group(*formatted_lines)
