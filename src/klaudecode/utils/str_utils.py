import re
from typing import Optional


def truncate_char(text: str, max_chars: int = 100, show_remaining: bool = False) -> str:
    if len(text) <= max_chars:
        return text

    truncated_content = text[:max_chars]
    if show_remaining:
        truncated_content += f'... + {len(text) - max_chars} chars'
    else:
        truncated_content += '...'
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

    old_len, new_len = len(old_text), len(new_text)

    # Find common prefix length
    prefix_len = 0
    max_prefix = min(old_len, new_len)
    while prefix_len < max_prefix and old_text[prefix_len] == new_text[prefix_len]:
        prefix_len += 1

    # Find common suffix length, but only compare the remaining parts
    suffix_len = 0
    old_remaining = old_len - prefix_len
    new_remaining = new_len - prefix_len
    max_suffix = min(old_remaining, new_remaining)

    # Compare from the end backwards, but only within the remaining parts
    while suffix_len < max_suffix:
        old_idx = old_len - 1 - suffix_len
        new_idx = new_len - 1 - suffix_len
        if old_text[old_idx] == new_text[new_idx]:
            suffix_len += 1
        else:
            break

    # Extract the inserted part
    start_idx = prefix_len
    end_idx = new_len - suffix_len
    return new_text[start_idx:end_idx]


def extract_xml_content(text: str, tag: str) -> str:
    """Extract content between XML tags"""
    pattern = re.compile(rf'<{re.escape(tag)}>(.*?)</{re.escape(tag)}>', re.DOTALL)
    match = pattern.search(text)
    return match.group(1) if match else ''
