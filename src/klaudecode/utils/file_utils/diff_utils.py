import difflib
import re
from typing import List, Tuple

from rich.console import Group
from rich.text import Text

from ...utils.str_utils import normalize_tabs
from .diff_renderer import DiffRenderer
from .diff_renderer import generate_char_level_diff as _generate_char_level_diff


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
    return _generate_char_level_diff(old_line, new_line)


def render_diff_lines(diff_lines: List[str], file_path: str = None, show_summary: bool = False) -> Group:
    """Render diff lines with color formatting for terminal display.

    Args:
        diff_lines: List of unified diff lines
        file_path: Optional file path to show in summary
        show_summary: Whether to show addition/removal summary

    Returns:
        Rich Group object with formatted diff content
    """
    renderer = DiffRenderer()
    return renderer.render_diff_lines(diff_lines, file_path, show_summary)
