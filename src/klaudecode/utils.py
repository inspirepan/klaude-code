

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
