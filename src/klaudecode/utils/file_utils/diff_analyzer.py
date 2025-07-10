import re
from typing import List

from .file_operations import get_relative_path_for_display


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
        summary_text = Text.assemble('Updated ', (display_path, 'bold'), ' with ')

        for i, part in enumerate(summary_parts):
            if i > 0:
                summary_text.append(' and ')

            words = part.split(' ', 1)
            if len(words) == 2:
                number, text = words
                summary_text.append(number, style='bold')
                summary_text.append(f' {text}')
            else:
                summary_text.append(part)

        return summary_text
