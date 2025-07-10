from pathlib import Path
from typing import List, Optional, Tuple, Union

from .directory_constants import DEFAULT_MAX_CHARS
from .directory_tree_builder import DirectoryTreeBuilder
from .gitignore_parser import GitIgnoreParser


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
