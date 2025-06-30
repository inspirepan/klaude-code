import fnmatch
from collections import deque
from pathlib import Path
from typing import List, Optional, Tuple, Union

# Directory structure constants
DEFAULT_MAX_CHARS = 40000
INDENT_SIZE = 2

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
    '*.jpg',
    '*.jpeg',
    '*.png',
    '*.gif',
    '*.bmp',
    '*.svg',
    '*.mp4',
    '*.mov',
    '*.avi',
    '*.mkv',
    '*.webm',
    '*.mp3',
    '*.wav',
    '*.flac',
    '*.ogg',
    '*.zip',
    '*.tar',
    '*.gz',
    '*.bz2',
    '*.xz',
    '*.7z',
    '*.pdf',
    '*.doc',
    '*.docx',
    '*.xls',
    '*.xlsx',
    '*.ppt',
    '*.pptx',
    '*.exe',
    '*.dll',
    '*.so',
    '*.dylib',
]


def parse_gitignore(gitignore_path: Union[str, Path]) -> List[str]:
    """Parse .gitignore file and return list of ignore patterns.

    Args:
        gitignore_path: Path to .gitignore file

    Returns:
        List of ignore patterns
    """
    patterns = []
    gitignore = Path(gitignore_path)

    if not gitignore.exists():
        return patterns

    try:
        with gitignore.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.startswith('!'):
                        continue
                    patterns.append(line)
    except Exception:
        pass

    return patterns


def get_effective_ignore_patterns(additional_patterns: Optional[List[str]] = None) -> List[str]:
    """Get effective ignore patterns by combining defaults with .gitignore.

    Args:
        additional_patterns: Additional patterns to include

    Returns:
        Combined list of ignore patterns
    """
    patterns = DEFAULT_IGNORE_PATTERNS.copy()

    gitignore_path = Path.cwd() / '.gitignore'
    gitignore_patterns = parse_gitignore(gitignore_path)
    patterns.extend(gitignore_patterns)

    if additional_patterns:
        patterns.extend(additional_patterns)

    return patterns


class TreeNode:
    """Represents a node in the directory tree."""

    def __init__(self, name: str, path: Union[str, Path], is_dir: bool, depth: int):
        self.name = name
        self.path = Path(path)
        self.is_dir = is_dir
        self.depth = depth
        self.children: List['TreeNode'] = []


def _should_ignore_path(item_path: Path, item_name: str, ignore_patterns: List[str], show_hidden: bool) -> bool:
    """Check if a path should be ignored based on patterns and settings.

    Args:
        item_path: Full path to the item
        item_name: Name of the item
        ignore_patterns: List of patterns to ignore
        show_hidden: Whether to show hidden files

    Returns:
        True if path should be ignored
    """
    if not show_hidden and item_name.startswith('.') and item_name not in ['.', '..']:
        return True

    for pattern in ignore_patterns:
        if pattern.endswith('/'):
            if fnmatch.fnmatch(item_name + '/', pattern) or fnmatch.fnmatch(str(item_path) + '/', pattern):
                return True
        else:
            if fnmatch.fnmatch(item_name, pattern) or fnmatch.fnmatch(str(item_path), pattern):
                return True
    return False


def _build_directory_tree(root_path: Union[str, Path], ignore_patterns: List[str], max_chars: int, max_depth: Optional[int], show_hidden: bool) -> Tuple[TreeNode, int, bool]:
    """Build directory tree using breadth-first traversal.

    Args:
        root_path: Root directory path
        ignore_patterns: Patterns to ignore
        max_chars: Maximum character limit
        max_depth: Maximum depth
        show_hidden: Whether to show hidden files

    Returns:
        Tuple of (root_node, path_count, truncated)
    """
    root_dir = Path(root_path)
    root = TreeNode(root_dir.name or str(root_dir), root_dir, True, 0)
    queue = deque([root])
    path_count = 0
    char_budget = max_chars if max_chars > 0 else float('inf')
    truncated = False

    while queue and char_budget > 0:
        current_node = queue.popleft()

        if max_depth is not None and current_node.depth >= max_depth:
            continue

        if not current_node.is_dir:
            continue

        try:
            items = [item.name for item in current_node.path.iterdir()]
        except (PermissionError, OSError):
            continue

        dirs = []
        files = []

        for item in items:
            item_path = current_node.path / item

            if _should_ignore_path(item_path, item, ignore_patterns, show_hidden):
                continue

            if item_path.is_dir():
                dirs.append(item)
            else:
                files.append(item)

        dirs.sort()
        files.sort()

        for item in dirs + files:
            item_path = current_node.path / item
            is_dir = item_path.is_dir()
            child_node = TreeNode(item, item_path, is_dir, current_node.depth + 1)
            current_node.children.append(child_node)
            path_count += 1

            estimated_chars = (child_node.depth * INDENT_SIZE) + len(child_node.name) + 3
            if char_budget - estimated_chars <= 0:
                truncated = True
                break
            char_budget -= estimated_chars

            if is_dir:
                queue.append(child_node)

        if truncated:
            break

    return root, path_count, truncated


def _format_tree_node(node: TreeNode) -> List[str]:
    """Format tree node and its children into display lines.

    Args:
        node: Tree node to format

    Returns:
        List of formatted lines
    """
    lines = []

    def traverse(current_node: TreeNode):
        if current_node.depth == 0:
            display_name = str(current_node.path) + '/' if current_node.is_dir else str(current_node.path)
            lines.append(f'- {display_name}')
        else:
            indent = '  ' * current_node.depth
            display_name = current_node.name + '/' if current_node.is_dir else current_node.name
            lines.append(f'{indent}- {display_name}')

        for child in current_node.children:
            traverse(child)

    traverse(node)
    return lines


def get_directory_structure(
    path: Union[str, Path], ignore_pattern: Optional[List[str]] = None, max_chars: int = DEFAULT_MAX_CHARS, max_depth: Optional[int] = None, show_hidden: bool = False
) -> Tuple[str, bool, int]:
    """Generate a text representation of directory structure.

    Uses breadth-first traversal to build tree structure, then formats output
    in depth-first manner for better readability.

    Args:
        path: Directory path to analyze
        ignore_pattern: Additional ignore patterns list (optional)
        max_chars: Maximum character limit, 0 means unlimited
        max_depth: Maximum depth, None means unlimited
        show_hidden: Whether to show hidden files

    Returns:
        Tuple[str, bool, int]: (content, truncated, path_count)
        - content: Formatted directory tree text
        - truncated: Whether truncated due to character limit
        - path_count: Number of path items included
    """
    dir_path = Path(path)

    if not dir_path.exists():
        return f'Path does not exist: {dir_path}', False, 0

    if not dir_path.is_dir():
        return f'Path is not a directory: {dir_path}', False, 0

    all_ignore_patterns = get_effective_ignore_patterns(ignore_pattern)

    root_node, path_count, truncated = _build_directory_tree(dir_path, all_ignore_patterns, max_chars, max_depth, show_hidden)

    lines = _format_tree_node(root_node)
    content = '\n'.join(lines)

    if truncated:
        content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    return content, truncated, path_count
