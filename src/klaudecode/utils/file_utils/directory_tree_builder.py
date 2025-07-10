import fnmatch
from collections import deque
from pathlib import Path
from typing import List, Optional, Tuple, Union

from .directory_constants import DEFAULT_MAX_CHARS, INDENT_SIZE
from .gitignore_parser import GitIgnoreParser


class TreeNode:
    def __init__(self, name: str, path: Union[str, Path], is_dir: bool, depth: int):
        self.name = name
        self.path = Path(path)
        self.is_dir = is_dir
        self.depth = depth
        self.children: List['TreeNode'] = []


class DirectoryTreeBuilder:
    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS, max_depth: Optional[int] = None, show_hidden: bool = False, additional_ignore_patterns: Optional[List[str]] = None):
        self.max_chars = max_chars
        self.max_depth = max_depth
        self.show_hidden = show_hidden
        self.ignore_patterns = GitIgnoreParser.get_effective_ignore_patterns(additional_ignore_patterns)

    def should_ignore_path(self, item_path: Path, item_name: str) -> bool:
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
        dir_path = Path(dir_path)

        if not dir_path.exists():
            return []

        if not dir_path.is_dir():
            return []

        root_node, _, _ = self.build_tree(dir_path)
        lines = []

        def traverse(current_node: TreeNode):
            path_str = str(current_node.path)
            if current_node.is_dir and not path_str.endswith('/'):
                path_str += '/'
            lines.append(path_str)
            for child in current_node.children:
                traverse(child)

        traverse(root_node)
        return lines
