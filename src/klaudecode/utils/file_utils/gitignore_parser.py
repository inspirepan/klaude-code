from pathlib import Path
from typing import List, Optional, Union

from .directory_constants import DEFAULT_IGNORE_PATTERNS


class GitIgnoreParser:
    @staticmethod
    def parse_gitignore(gitignore_path: Union[str, Path]) -> List[str]:
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
        patterns = DEFAULT_IGNORE_PATTERNS.copy()

        gitignore_path = Path.cwd() / '.gitignore'
        gitignore_patterns = cls.parse_gitignore(gitignore_path)
        patterns.extend(gitignore_patterns)

        if additional_patterns:
            patterns.extend(additional_patterns)

        return patterns
