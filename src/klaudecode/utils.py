import fnmatch
import re
from pathlib import Path
from typing import List, Optional


def _parse_gitignore(gitignore_path: Path) -> List[str]:
    """Parse .gitignore file and return list of ignore patterns"""
    patterns = []
    if not gitignore_path.exists():
        return patterns

    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)
    except Exception:
        pass

    return patterns


def _should_ignore(path: Path, ignore_patterns: List[str], base_path: Path) -> bool:
    """Check if path should be ignored"""
    if not ignore_patterns:
        return False

    relative_path = path.relative_to(base_path)
    path_str = str(relative_path)

    for pattern in ignore_patterns:
        # Simple pattern matching implementation
        if pattern.endswith('/'):
            # Directory matching
            pattern_name = pattern[:-1]
            if path.is_dir() and (path_str == pattern_name or path_str.startswith(pattern) or path.name == pattern_name):
                return True
        elif '*' in pattern:
            # Wildcard matching
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
        else:
            # Exact matching
            if path_str == pattern or path.name == pattern:
                return True

    return False


def _build_tree(path: Path, ignore_patterns: List[str], base_path: Path, indent: int = 0) -> List[str]:
    """Recursively build directory tree"""
    result = []

    if _should_ignore(path, ignore_patterns, base_path):
        return result

    # Add current item
    prefix = '  ' * indent
    if path.is_dir():
        result.append(f'{prefix}- {path.name}/')

        # Get and sort child items
        try:
            children = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for child in children:
                if not _should_ignore(child, ignore_patterns, base_path):
                    result.extend(_build_tree(child, ignore_patterns, base_path, indent + 1))
        except PermissionError:
            pass
    else:
        result.append(f'{prefix}- {path.name}')

    return result


def get_directory_structure(path: str, ignore_pattern: Optional[List[str]] = None, max_chars: int = 40000, max_lines: int = 0) -> tuple[str, str]:
    """
    Get directory structure with character and line limits, returns full result and truncated human-friendly result

    Args:
        path: Directory path
        ignore_pattern: Additional ignore patterns list (optional)
        max_chars: Maximum character limit, 0 means no limit
        max_lines: Maximum line limit, 0 means no limit

    Returns:
        tuple[str, str]: (full result, human-friendly truncated result)
    """
    path_obj = Path(path).resolve()

    if not path_obj.exists():
        return f'- {path} (path does not exist)', f'- {path} (path does not exist)'

    # Read .gitignore file
    gitignore_path = path_obj / '.gitignore'
    ignore_patterns = _parse_gitignore(gitignore_path)

    # Add default ignore patterns (Git related)
    default_ignores = ['.git/', '.gitignore']
    ignore_patterns.extend(default_ignores)

    # Add additional ignore patterns
    if ignore_pattern:
        ignore_patterns.extend(ignore_pattern)

    # Build file tree
    result = [f'- {path_obj.name}/']

    # Get and sort child items
    try:
        children = sorted(path_obj.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        for child in children:
            if not _should_ignore(child, ignore_patterns, path_obj):
                result.extend(_build_tree(child, ignore_patterns, path_obj, 1))
    except PermissionError:
        result.append('  - (permission denied)')

    full_content = '\n'.join(result)
    lines = full_content.split('\n')

    # Create human-friendly truncated version (line limit of 20 lines)
    human_line_limit = 20
    if max_lines > 0:
        human_line_limit = min(max_lines, human_line_limit)

    if len(lines) > human_line_limit + 5:  # If exceeds limit + buffer
        human_result = '\n'.join(lines[:human_line_limit])
        remaining_lines = len(lines) - human_line_limit
        human_result += f'\n... + {remaining_lines} lines'
    else:
        human_result = full_content

    # If no character limit or content doesn't exceed limit, return full content
    if max_chars <= 0 or len(full_content) <= max_chars:
        return full_content, human_result

    # Smart truncation: don't truncate in the middle of items
    truncated_lines = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > max_chars:  # +1 for newline
            break
        truncated_lines.append(line)
        current_length += len(line) + 1

    truncated_content = '\n'.join(truncated_lines)
    truncated_content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    # Update human_result if character truncation is more restrictive than line truncation
    if len(truncated_content) < len(human_result):
        human_result = truncated_content

    return truncated_content, human_result


def truncate_end_text(text: str, max_lines: int = 15) -> str:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text

    truncated_lines = lines[:max_lines]
    remaining_lines = len(lines) - max_lines
    truncated_content = '\n'.join(truncated_lines)
    truncated_content += f'\n... + {remaining_lines} lines'
    return truncated_content


def sanitize_filename(text: str, max_length: int = 20) -> str:
    if not text:
        return 'untitled'
    text = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\s.-]', '_', text)
    text = re.sub(r'\s+', '_', text)
    text = text.strip('_')
    if not text:
        return 'untitled'
    if len(text) > max_length:
        text = text[:max_length].rstrip('_')

    return text
