import fnmatch
import os
import re
from collections import deque
from typing import List, Optional, Tuple

DEFAULT_IGNORE_PATTERNS = [
    'node_modules',
    '.git',
    '.svn',
    '.hg',
    '.bzr',
    '__pycache__',
    '.pytest_cache',
    '.mypy_cache',
    '.tox',
    '.venv',
    'venv',
    '.env',
    '.virtualenv',
    'dist',
    'build',
    'target',
    'out',
    'bin',
    'obj',
    '.DS_Store',
    'Thumbs.db',
    '*.tmp',
    '*.temp',
    '*.log',
    '*.cache',
    '*.lock',
]


def get_directory_structure(
    path: str, ignore_pattern: Optional[List[str]] = None, max_chars: int = 40000, max_depth: Optional[int] = None, show_hidden: bool = False
) -> Tuple[str, bool, int]:
    """
    Generate a text representation of directory structure using breadth-first traversal to build tree structure, then format output in depth-first manner.

    Args:
        path: Directory path
        ignore_pattern: Additional ignore patterns list (optional)
        max_chars: Maximum character limit, 0 means unlimited
        max_depth: Maximum depth, None means unlimited
        show_hidden: Whether to show hidden files, None means auto-detect

    Returns:
        Tuple[str, bool, int]: (content, truncated, path_count)
        - content: Formatted directory tree text
        - truncated: Whether truncated due to character limit
        - path_count: Number of path items included
    """
    if not os.path.exists(path):
        return f'Path does not exist: {path}', False, 0

    if not os.path.isdir(path):
        return f'Path is not a directory: {path}', False, 0

    # Prepare ignore patterns
    all_ignore_patterns = DEFAULT_IGNORE_PATTERNS.copy()
    if ignore_pattern:
        all_ignore_patterns.extend(ignore_pattern)

    # Tree node structure
    class TreeNode:
        def __init__(self, name: str, path: str, is_dir: bool, depth: int):
            self.name = name
            self.path = path
            self.is_dir = is_dir
            self.depth = depth
            self.children = []

    def should_ignore(item_path: str, item_name: str) -> bool:
        """Check if this item should be ignored"""
        # Check hidden files
        if not show_hidden and item_name.startswith('.') and item_name not in ['.', '..']:
            return True

        # Check ignore patterns
        for pattern in all_ignore_patterns:
            if pattern.endswith('/'):
                # Directory pattern
                if fnmatch.fnmatch(item_name + '/', pattern) or fnmatch.fnmatch(item_path + '/', pattern):
                    return True
            else:
                # File pattern
                if fnmatch.fnmatch(item_name, pattern) or fnmatch.fnmatch(item_path, pattern):
                    return True
        return False

    # Breadth-first traversal to build tree structure
    root = TreeNode(os.path.basename(path) or path, path, True, 0)
    queue = deque([root])
    path_count = 0
    char_budget = max_chars if max_chars > 0 else float('inf')
    truncated = False

    while queue and char_budget > 0:
        current_node = queue.popleft()

        # Check depth limit
        if max_depth is not None and current_node.depth >= max_depth:
            continue

        if not current_node.is_dir:
            continue

        try:
            items = os.listdir(current_node.path)
        except (PermissionError, OSError):
            continue

        # Separate directories and files, then sort
        dirs = []
        files = []

        for item in items:
            item_path = os.path.join(current_node.path, item)

            if should_ignore(item_path, item):
                continue

            if os.path.isdir(item_path):
                dirs.append(item)
            else:
                files.append(item)

        # Sort: directories first, then files
        dirs.sort()
        files.sort()

        # Create child nodes
        for item in dirs + files:
            item_path = os.path.join(current_node.path, item)
            is_dir = os.path.isdir(item_path)
            child_node = TreeNode(item, item_path, is_dir, current_node.depth + 1)
            current_node.children.append(child_node)
            path_count += 1

            # Estimate character consumption (rough estimate: indentation + name + newline)
            estimated_chars = (child_node.depth * 2) + len(child_node.name) + 3
            if char_budget - estimated_chars <= 0:
                truncated = True
                break
            char_budget -= estimated_chars

            # If it's a directory, add to queue for further traversal
            if is_dir:
                queue.append(child_node)

        if truncated:
            break

    # Depth-first format output
    def format_tree() -> str:
        lines = []

        def traverse(node: TreeNode):
            if node.depth == 0:
                # Root directory - show absolute path
                display_name = node.path + '/' if node.is_dir else node.path
                lines.append(f'- {display_name}')
            else:
                # Sub-items
                indent = '  ' * node.depth
                display_name = node.name + '/' if node.is_dir else node.name
                lines.append(f'{indent}- {display_name}')

            # Recursively process all child nodes
            for child in node.children:
                traverse(child)

        traverse(root)
        return '\n'.join(lines)

    content = format_tree()

    # If truncated, add truncation information
    if truncated:
        content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    return content, truncated, path_count


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
