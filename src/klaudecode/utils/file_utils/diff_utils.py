import difflib
import re
from typing import List, Tuple

from rich.console import Group
from rich.table import Table
from rich.text import Text

from ...tui import ColorStyle
from ...utils.str_utils import normalize_tabs
from .file_operations import get_relative_path_for_display


def generate_diff_lines(old_content: str, new_content: str) -> List[str]:
    """Generate unified diff lines between old and new content.

    Args:
        old_content: Original content
        new_content: Modified content

    Returns:
        List of diff lines in unified format
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
        )
    )

    # Add "\ No newline at end of file" messages if needed
    old_ends_with_newline = old_content.endswith('\n')
    new_ends_with_newline = new_content.endswith('\n')

    # If there are diff lines and newline status differs, add the message
    if diff_lines and (old_ends_with_newline != new_ends_with_newline):
        # Find the last line that was changed
        for i in range(len(diff_lines) - 1, -1, -1):
            line = diff_lines[i]
            if line.startswith('-') and not old_ends_with_newline:
                # Insert after the removed line
                diff_lines.insert(i + 1, '\\ No newline at end of file\n')
                break
            elif line.startswith('+') and not new_ends_with_newline:
                # Insert after the added line
                diff_lines.insert(i + 1, '\\ No newline at end of file\n')
                break

    return diff_lines


def generate_snippet_from_diff(diff_lines: List[str]) -> str:
    """Generate a snippet from diff lines showing context and new content.

    Only includes context lines (' ') and added lines ('+') in line-number→line-content format.

    Args:
        diff_lines: List of unified diff lines

    Returns:
        Formatted snippet string
    """
    if not diff_lines:
        return ''

    new_line_num = 1
    snippet_lines = []

    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                new_line_num = int(match.group(2))
        elif line.startswith('-'):
            continue
        elif line.startswith('+'):
            added_line = line[1:].rstrip('\n\r')
            snippet_lines.append(f'{new_line_num}→{normalize_tabs(added_line)}')
            new_line_num += 1
        elif line.startswith(' '):
            context_line = line[1:].rstrip('\n\r')
            snippet_lines.append(f'{new_line_num}→{normalize_tabs(context_line)}')
            new_line_num += 1
        elif line.startswith('\\'):
            # Skip "\ No newline at end of file" in snippet generation
            continue

    return '\n'.join(snippet_lines)


def generate_char_level_diff(old_line: str, new_line: str) -> Tuple[Text, Text]:
    """Generate character-level diff for two lines.

    Args:
        old_line: Original line content
        new_line: Modified line content

    Returns:
        Tuple of (styled_old_line, styled_new_line)
    """
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
            # No corresponding text in new line
        elif tag == 'insert':
            # No corresponding text in old line
            new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR)
        elif tag == 'replace':
            old_text.append(old_segment, style=ColorStyle.DIFF_REMOVED_CHAR)
            new_text.append(new_segment, style=ColorStyle.DIFF_ADDED_CHAR)

    return old_text, new_text


def render_diff_lines(diff_lines: List[str], file_path: str = None, show_summary: bool = False) -> Group:
    """Render diff lines with color formatting for terminal display.

    Args:
        diff_lines: List of unified diff lines
        file_path: Optional file path to show in summary
        show_summary: Whether to show addition/removal summary

    Returns:
        Rich Group object with formatted diff content
    """
    if not diff_lines:
        return Group()

    # Calculate additions and removals if summary is requested
    summary_renderable = None
    if show_summary and file_path:
        additions = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
        removals = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))

        # Create summary line
        summary_parts = []
        if additions > 0:
            summary_parts.append(f'{additions} addition{"s" if additions != 1 else ""}')
        if removals > 0:
            summary_parts.append(f'{removals} removal{"s" if removals != 1 else ""}')

        if summary_parts:
            display_path = get_relative_path_for_display(file_path)
            # Create styled summary using Text.assemble
            summary_text = Text.assemble('Updated ', (display_path, 'bold'), ' with ')

            for i, part in enumerate(summary_parts):
                if i > 0:
                    summary_text.append(' and ')

                # Extract number and text from part like "1 addition" or "2 removals"
                words = part.split(' ', 1)
                if len(words) == 2:
                    number, text = words
                    summary_text.append(number, style='bold')
                    summary_text.append(f' {text}')
                else:
                    summary_text.append(part)

            summary_renderable = summary_text

    old_line_num = 1
    new_line_num = 1
    width = 3

    grid = Table.grid(padding=(0, 0))
    grid.add_column()
    grid.add_column()
    grid.add_column(overflow='fold')

    add_line_symbol = Text('+ ')
    add_line_symbol.stylize(ColorStyle.DIFF_ADDED_LINE)
    remove_line_symbol = Text('- ')
    remove_line_symbol.stylize(ColorStyle.DIFF_REMOVED_LINE)
    context_line_symbol = Text('  ')

    def _is_single_line_change(start_idx: int) -> bool:
        """Check if this is a single line removal followed by single line addition between context lines."""
        if start_idx == 0 or start_idx >= len(diff_lines) - 2:
            return False

        # Check if previous line is context or start of hunk
        prev_line = diff_lines[start_idx - 1]
        if not (prev_line.startswith(' ') or prev_line.startswith('@@')):
            return False

        # Check if current is single '-' and next is single '+'
        current_line = diff_lines[start_idx]
        next_line = diff_lines[start_idx + 1]
        if not (current_line.startswith('-') and next_line.startswith('+')):
            return False

        # Check if the line after '+' is context or end of diff
        if start_idx + 2 < len(diff_lines):
            after_plus = diff_lines[start_idx + 2]
            if not (after_plus.startswith(' ') or after_plus.startswith('@@') or after_plus.startswith('---') or after_plus.startswith('+++')):
                return False

        return True

    # Parse the diff to find consecutive remove/add pairs
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]

        if line.startswith('---') or line.startswith('+++'):
            i += 1
            continue
        elif line.startswith('@@'):
            match = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if match:
                old_line_num = int(match.group(1))
                new_line_num = int(match.group(2))
            i += 1
            continue
        elif line.startswith('-'):
            # Check if next line is an add (indicating a modification)
            removed_line = line[1:].strip('\n\r')
            if i + 1 < len(diff_lines) and diff_lines[i + 1].startswith('+'):
                added_line = diff_lines[i + 1][1:].strip('\n\r')

                # Only do character-level diff for single line changes between context lines
                if _is_single_line_change(i):
                    styled_old, styled_new = generate_char_level_diff(removed_line, added_line)
                    grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, styled_old)
                    grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, styled_new)
                else:
                    # Use simple line-level styling for consecutive changes
                    old_text = Text(normalize_tabs(removed_line))
                    old_text.stylize(ColorStyle.DIFF_REMOVED_LINE)
                    new_text = Text(normalize_tabs(added_line))
                    new_text.stylize(ColorStyle.DIFF_ADDED_LINE)
                    grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, old_text)
                    grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, new_text)

                old_line_num += 1
                new_line_num += 1
                i += 2  # Skip both lines
            else:
                # Pure removal
                text = Text(normalize_tabs(removed_line))
                text.stylize(ColorStyle.DIFF_REMOVED_LINE)
                grid.add_row(Text(f'{old_line_num:{width}d} '), remove_line_symbol, text)
                old_line_num += 1
                i += 1
        elif line.startswith('+'):
            # Pure addition (not part of a modification pair)
            added_line = line[1:].strip('\n\r')
            text = Text(normalize_tabs(added_line))
            text.stylize(ColorStyle.DIFF_ADDED_LINE)
            grid.add_row(Text(f'{new_line_num:{width}d} '), add_line_symbol, text)
            new_line_num += 1
            i += 1
        elif line.startswith(' '):
            context_line = line[1:].strip('\n\r')
            text = Text(normalize_tabs(context_line))
            text.stylize(ColorStyle.CONTEXT_LINE)
            grid.add_row(Text(f'{new_line_num:{width}d} '), context_line_symbol, text)
            old_line_num += 1
            new_line_num += 1
            i += 1
        elif line.startswith('\\'):
            # Handle "\ No newline at end of file" as context line
            no_newline_text = Text(line.strip())
            no_newline_text.stylize(ColorStyle.CONTEXT_LINE)
            grid.add_row('', Text('  '), no_newline_text)
            i += 1
        else:
            grid.add_row('', '', Text(line))
            i += 1

    # Return with or without summary
    if summary_renderable:
        return Group(summary_renderable, grid)
    else:
        return grid
