import re
from typing import Optional


def truncate_end_text(text: str, max_lines: int = 15) -> str:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text

    truncated_lines = lines[:max_lines]
    remaining_lines = len(lines) - max_lines
    truncated_content = '\n'.join(truncated_lines)
    truncated_content += f'\n... + {remaining_lines} lines'
    return truncated_content


def sanitize_filename(text: str, max_length: Optional[int] = None) -> str:
    if not text:
        return 'untitled'
    text = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\s.-]', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = text.strip('_')
    if not text:
        return 'untitled'
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip('_')

    return text


def format_relative_time(timestamp):
    from datetime import datetime

    now = datetime.now()
    created = datetime.fromtimestamp(timestamp)
    diff = now - created

    if diff.days > 1:
        return f'{diff.days} days ago'
    elif diff.days == 1:
        return '1 day ago'
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f'{hours}h ago'
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f'{minutes}m ago'
    else:
        return 'just now'


def normalize_tabs(text: str, tab_size: int = 4) -> str:
    return text.replace('\t', ' ' * tab_size)


def get_inserted_text(old_text: str, new_text: str) -> str:
    """Get the inserted text from old_text to new_text.

    Compare two strings to find the inserted part. Supports insertion in the middle of strings.

    Args:
        old_text: Original text
        new_text: New text

    Returns:
        The inserted text part
    """
    if len(new_text) <= len(old_text):
        return ''

    prefix_len = 0
    for i in range(min(len(old_text), len(new_text))):
        if old_text[i] == new_text[i]:
            prefix_len += 1
        else:
            break

    suffix_len = 0
    for i in range(1, min(len(old_text) - prefix_len, len(new_text) - prefix_len) + 1):
        if old_text[-i] == new_text[-i]:
            suffix_len += 1
        else:
            break

    return new_text[prefix_len : len(new_text) - suffix_len]
