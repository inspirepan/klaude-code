import fnmatch
import re
from pathlib import Path
from typing import List, Optional, Tuple


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


def _matches_recursive_pattern(path_str: str, pattern: str) -> bool:
    """Check if path matches pattern with recursive directory support"""
    if '/' not in pattern:
        return False

    # Split pattern into directory part and file part
    pattern_parts = pattern.split('/')
    if len(pattern_parts) != 2:
        return False

    dir_pattern, file_pattern = pattern_parts
    path_parts = path_str.split('/')

    # Look for the directory pattern at any level
    for i in range(len(path_parts) - 1):
        if fnmatch.fnmatch(path_parts[i], dir_pattern):
            # Check if the remaining path matches the file pattern
            remaining_path = '/'.join(path_parts[i + 1 :])
            if fnmatch.fnmatch(remaining_path, file_pattern):
                return True

    return False


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
            # Wildcard matching - try both existing and recursive matching
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path.name, pattern) or _matches_recursive_pattern(path_str, pattern):
                return True
        else:
            # Exact matching
            if path_str == pattern or path.name == pattern:
                return True

    return False


def _build_tree(path: Path, ignore_patterns: List[str], base_path: Path, char_budget: int, indent: int = 0) -> Tuple[List[str], int, bool]:
    """Recursively build directory tree with character budget"""
    result = []
    truncated = False

    if _should_ignore(path, ignore_patterns, base_path):
        return result, char_budget, False

    # Add current item
    prefix = '  ' * indent
    if path.is_dir():
        line = f'{prefix}- {path.name}/'
        line_cost = len(line) + 1  # +1 for newline

        if char_budget != float('inf') and char_budget < line_cost:
            return result, char_budget, True

        result.append(line)
        if char_budget != float('inf'):
            char_budget -= line_cost

        # Get and sort child items
        try:
            children = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for child in children:
                if not _should_ignore(child, ignore_patterns, base_path):
                    child_result, char_budget, child_truncated = _build_tree(child, ignore_patterns, base_path, char_budget, indent + 1)
                    result.extend(child_result)
                    if child_truncated:
                        truncated = True
                        break
        except PermissionError:
            pass
    else:
        line = f'{prefix}- {path.name}'
        line_cost = len(line) + 1  # +1 for newline

        if char_budget != float('inf') and char_budget < line_cost:
            return result, char_budget, True

        result.append(line)
        if char_budget != float('inf'):
            char_budget -= line_cost

    return result, char_budget, truncated


def get_directory_structure(path: str, ignore_pattern: Optional[List[str]] = None, max_chars: int = 40000) -> Tuple[str, bool, int]:
    """
    Get directory structure with character limit, returns full result

    Args:
        path: Directory path
        ignore_pattern: Additional ignore patterns list (optional)
        max_chars: Maximum character limit, 0 means no limit

    Returns:
        str: full result
    """
    path_obj = Path(path).resolve()

    if not path_obj.exists():
        return '(path does not exist)', False, 0

    # Read .gitignore file
    gitignore_path = path_obj / '.gitignore'
    ignore_patterns = _parse_gitignore(gitignore_path)

    # Add default ignore patterns
    default_ignores = ['.git/', '.gitignore', '.venv/', '.env', '.DS_Store', '__pycache__/']
    ignore_patterns.extend(default_ignores)

    # Add additional ignore patterns
    if ignore_pattern:
        ignore_patterns.extend(ignore_pattern)

    # Build file tree with character budget
    root_line = f'- {path_obj.name}/'
    result = [root_line]

    if max_chars <= 0:
        # No character limit
        char_budget = float('inf')
    else:
        # Reserve space for root line and potential truncation message
        char_budget = max_chars - len(root_line) - 1  # -1 for newline

    overall_truncated = False

    # Get and sort child items
    try:
        children = sorted(path_obj.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        for child in children:
            if not _should_ignore(child, ignore_patterns, path_obj):
                if char_budget == float('inf'):
                    child_result, _, child_truncated = _build_tree(child, ignore_patterns, path_obj, float('inf'), 1)
                else:
                    child_result, char_budget, child_truncated = _build_tree(child, ignore_patterns, path_obj, char_budget, 1)

                result.extend(child_result)
                if child_truncated:
                    overall_truncated = True
                    break
    except PermissionError as e:
        perm_line = f'  - (permission denied: {e})'
        perm_cost = len(perm_line) + 1
        if char_budget == float('inf') or char_budget >= perm_cost:
            result.append(perm_line)
        else:
            overall_truncated = True

    content = '\n'.join(result)
    path_count = len(result)

    if overall_truncated:
        content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    return content, overall_truncated, path_count


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
