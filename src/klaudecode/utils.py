import re


def truncate_text(text: str, max_lines: int = 15) -> str:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text
    # If content has more than max_lines, truncate and show summary
    truncated_lines = lines[:max_lines]
    remaining_lines = len(lines) - max_lines
    # Add truncation indicator
    truncated_content = "\n".join(truncated_lines)
    truncated_content += f"\n... + {remaining_lines} lines"
    return truncated_content


def sanitize_filename(text: str, max_length: int = 20) -> str:
    if not text:
        return "untitled"
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    if not text:
        return "untitled"
    if len(text) > max_length:
        text = text[:max_length].rstrip()

    return text
