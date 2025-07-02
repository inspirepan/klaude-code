import glob as python_glob
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

DEFAULT_MAX_DEPTH = 10
DEFAULT_TIMEOUT = 30


class FileGlob:
    """
    Skip hidden files and directories.
    Do NOT skip .gitignore
    """

    @classmethod
    def validate_glob_pattern(cls, pattern: str) -> Optional[str]:
        try:
            if not pattern.strip():
                return 'Pattern cannot be empty'

            import fnmatch

            fnmatch.translate(pattern)
            return None
        except Exception as e:
            return f'Invalid glob pattern: {str(e)}'

    @classmethod
    def search_files(cls, pattern: str, path: str) -> List[str]:
        files = []

        if cls._has_fd():
            command = cls._build_fd_command(pattern, path)
            stdout, stderr, return_code = cls._execute_command(command)

            if return_code == 0 and stdout.strip():
                files = [cls.truncate_fd_path(line) for line in stdout.strip().split('\n') if line.strip()]

        if not files:
            files = cls._python_glob_search(pattern, path)

        if not files:
            return []

        try:
            files.sort(key=lambda f: Path(f).stat().st_mtime, reverse=True)
        except OSError:
            files.sort()
        return files

    @classmethod
    def _has_fd(cls) -> bool:
        return shutil.which('fd') is not None

    @classmethod
    def _build_fd_command(cls, pattern: str, path: str) -> list[str]:
        args = ['fd', '--type', 'f', '--glob', '--no-ignore', '-a']
        args.extend(['--max-depth', str(DEFAULT_MAX_DEPTH)])
        args.extend(['--exclude', '.*'])
        args.extend([pattern, path])
        return args

    @classmethod
    def _execute_command(cls, command: list[str]) -> tuple[str, str, int]:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=DEFAULT_TIMEOUT, cwd=Path.cwd())
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return '', f'Search timed out after {DEFAULT_TIMEOUT} seconds', 1
        except Exception as e:
            return '', f'Command execution failed: {str(e)}', 1

    @classmethod
    def truncate_fd_path(cls, path: str) -> str:
        path = path.strip()
        if path.startswith('./'):
            path = path[2:]
        return path

    @classmethod
    def _python_glob_search(cls, pattern: str, path: str) -> list[str]:
        try:
            search_path = Path(path) if path != '.' else Path.cwd()

            # Construct the full glob pattern
            if pattern.startswith('/'):
                # Absolute pattern
                glob_pattern = pattern
            else:
                # Relative pattern
                glob_pattern = str(search_path / pattern)

            # Use glob with recursive=True to handle ** patterns
            matches = python_glob.glob(glob_pattern, recursive=True)

            # Filter out directories and apply ignore patterns
            filtered_matches = []

            for match in matches:
                match_path = Path(match)

                # Only include files, not directories
                if not match_path.is_file():
                    continue

                # Skip hidden files and directories
                if any(part.startswith('.') for part in match_path.parts):
                    continue

                # Skip ignored patterns
                filtered_matches.append(str(match_path))

            return sorted(filtered_matches)

        except Exception:
            return []

    @classmethod
    def _should_ignore_file(cls, file_path: Path, ignore_pattern: str) -> bool:
        """Check if file should be ignored based on gitignore-style pattern."""
        import fnmatch

        file_str = str(file_path)
        relative_path = str(file_path.relative_to(Path.cwd())) if file_path.is_absolute() else file_str

        # Handle directory patterns ending with /
        if ignore_pattern.endswith('/'):
            # Check if any parent directory matches
            for parent in file_path.parents:
                if fnmatch.fnmatch(parent.name, ignore_pattern.rstrip('/')):
                    return True
            return False

        # Handle file extension patterns like *.py[oc]
        if ignore_pattern.startswith('*.'):
            return fnmatch.fnmatch(file_path.name, ignore_pattern)

        # Handle patterns with wildcards
        if '*' in ignore_pattern or '?' in ignore_pattern or '[' in ignore_pattern:
            return fnmatch.fnmatch(relative_path, ignore_pattern) or fnmatch.fnmatch(file_path.name, ignore_pattern)

        # Handle exact matches
        return ignore_pattern in file_path.parts or ignore_pattern == file_path.name or relative_path == ignore_pattern
