import glob as python_glob
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from .file_utils import DEFAULT_IGNORE_PATTERNS

DEFAULT_MAX_DEPTH = 10
DEFAULT_TIMEOUT = 30


class FileSearcher:
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
                files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]

        if not files and cls._has_find():
            command = cls._build_find_command(pattern, path)
            stdout, stderr, return_code = cls._execute_command(command)

            if return_code == 0 and stdout.strip():
                files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]

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
    def _has_find(cls) -> bool:
        return shutil.which('find') is not None

    @classmethod
    def _build_fd_command(cls, pattern: str, path: str) -> list[str]:
        args = ['fd', '--type', 'f', '--glob', '--hidden', '--no-ignore']
        args.extend(['--max-depth', str(DEFAULT_MAX_DEPTH)])

        for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
            args.extend(['--exclude', ignore_pattern])

        args.extend(['--exclude', '.*'])
        args.extend([pattern, path])
        return args

    @classmethod
    def _build_find_command(cls, pattern: str, path: str) -> list[str]:
        args = ['find', path, '-type', 'f']
        args.extend(['-maxdepth', str(DEFAULT_MAX_DEPTH)])
        
        # Use -name for simple patterns, -path for complex patterns
        if '/' in pattern:
            # For patterns with paths like "src/*.py", use -path
            args.extend(['-path', f'*{pattern}'])
        else:
            # For simple patterns like "*.py", use -name
            args.extend(['-name', pattern])

        args.extend(['!', '-name', '.*'])

        for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
            if ignore_pattern.startswith('*.'):
                args.extend(['!', '-name', ignore_pattern])
            else:
                args.extend(['!', '-path', f'*/{ignore_pattern}/*'])

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
                should_ignore = False
                for ignore_pattern in DEFAULT_IGNORE_PATTERNS:
                    if ignore_pattern.startswith('*.'):
                        # File extension pattern
                        if match_path.name.endswith(ignore_pattern[1:]):
                            should_ignore = True
                            break
                    else:
                        # Directory pattern
                        if ignore_pattern in match_path.parts:
                            should_ignore = True
                            break
                
                if not should_ignore:
                    filtered_matches.append(str(match_path))
            
            return sorted(filtered_matches)

        except Exception:
            return []
