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


class GitIgnoreParser:
    """Handles parsing and management of .gitignore patterns."""

    @staticmethod
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

    @classmethod
    def get_effective_ignore_patterns(cls, additional_patterns: Optional[List[str]] = None) -> List[str]:
        """Get effective ignore patterns by combining defaults with .gitignore.

        Args:
            additional_patterns: Additional patterns to include

        Returns:
            Combined list of ignore patterns
        """
        patterns = DEFAULT_IGNORE_PATTERNS.copy()

        gitignore_path = Path.cwd() / '.gitignore'
        gitignore_patterns = cls.parse_gitignore(gitignore_path)
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


class DirectoryTreeBuilder:
    """Builds and formats directory tree structures."""

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS, max_depth: Optional[int] = None, show_hidden: bool = False, additional_ignore_patterns: Optional[List[str]] = None):
        self.max_chars = max_chars
        self.max_depth = max_depth
        self.show_hidden = show_hidden
        self.ignore_patterns = GitIgnoreParser.get_effective_ignore_patterns(additional_ignore_patterns)

    def should_ignore_path(self, item_path: Path, item_name: str) -> bool:
        """Check if a path should be ignored based on patterns and settings.

        Args:
            item_path: Full path to the item
            item_name: Name of the item

        Returns:
            True if path should be ignored
        """
        if not self.show_hidden and item_name.startswith('.') and item_name not in ['.', '..']:
            return True

        for pattern in self.ignore_patterns:
            if pattern.endswith('/'):
                if fnmatch.fnmatch(item_name + '/', pattern) or fnmatch.fnmatch(str(item_path) + '/', pattern):
                    return True
            else:
                if fnmatch.fnmatch(item_name, pattern) or fnmatch.fnmatch(str(item_path), pattern):
                    return True
        return False

    def build_tree(self, root_path: Union[str, Path]) -> Tuple[TreeNode, int, bool]:
        """Build directory tree using breadth-first traversal.

        Args:
            root_path: Root directory path

        Returns:
            Tuple of (root_node, path_count, truncated)
        """
        root_dir = Path(root_path)
        root = TreeNode(root_dir.name or str(root_dir), root_dir, True, 0)
        queue = deque([root])
        path_count = 0
        char_budget = self.max_chars if self.max_chars > 0 else float('inf')
        truncated = False

        while queue and char_budget > 0:
            current_node = queue.popleft()

            if self.max_depth is not None and current_node.depth >= self.max_depth:
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

                if self.should_ignore_path(item_path, item):
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

    @staticmethod
    def build_indent_lines(node: TreeNode) -> List[str]:
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

    def get_directory_structure(self, path: Union[str, Path]) -> Tuple[str, bool, int]:
        """Generate a text representation of directory structure.

        Uses breadth-first traversal to build tree structure, then formats output
        in depth-first manner for better readability.

        Args:
            path: Directory path to analyze

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

        root_node, path_count, truncated = self.build_tree(dir_path)
        lines = self.build_indent_lines(root_node)
        content = '\n'.join(lines)

        if truncated:
            content += f'\n... (truncated at {self.max_chars} characters, use LS tool with specific paths to explore more)'

        return content, truncated, path_count

    def get_file_list(self, dir_path: Union[str, Path]) -> List[str]:
        """
        Get absolute file and dir paths from directory tree.
        Args:
            dir_path: Directory path to analyze

        Returns:
            List of absolute file and dir paths
        """
        dir_path = Path(dir_path)

        if not dir_path.exists():
            return []

        if not dir_path.is_dir():
            return []

        root_node, _, _ = self.build_tree(dir_path)
        lines = []

        def traverse(current_node: TreeNode):
            lines.append(str(current_node.path))
            for child in current_node.children:
                traverse(child)

        traverse(root_node)
        return lines


# Backward compatibility functions
def parse_gitignore(gitignore_path: Union[str, Path]) -> List[str]:
    """Parse .gitignore file and return list of ignore patterns.

    DEPRECATED: Use GitIgnoreParser.parse_gitignore() instead.
    """
    return GitIgnoreParser.parse_gitignore(gitignore_path)


def get_effective_ignore_patterns(additional_patterns: Optional[List[str]] = None) -> List[str]:
    """Get effective ignore patterns by combining defaults with .gitignore.

    DEPRECATED: Use GitIgnoreParser.get_effective_ignore_patterns() instead.
    """
    return GitIgnoreParser.get_effective_ignore_patterns(additional_patterns)


def get_directory_structure(
    path: Union[str, Path], ignore_pattern: Optional[List[str]] = None, max_chars: int = DEFAULT_MAX_CHARS, max_depth: Optional[int] = None, show_hidden: bool = False
) -> Tuple[str, bool, int]:
    """Generate a text representation of directory structure.
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
    builder = DirectoryTreeBuilder(max_chars=max_chars, max_depth=max_depth, show_hidden=show_hidden, additional_ignore_patterns=ignore_pattern)
    return builder.get_directory_structure(path)
