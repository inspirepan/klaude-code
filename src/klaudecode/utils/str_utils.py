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
