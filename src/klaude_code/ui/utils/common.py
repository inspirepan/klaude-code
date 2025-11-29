import re
import subprocess
from pathlib import Path

LEADING_NEWLINES_REGEX = re.compile(r"^\n{2,}")


def remove_leading_newlines(text: str) -> str:
    return text.lstrip("\n")


def format_number(tokens: int) -> str:
    if tokens < 1000:
        return f"{tokens}"
    elif tokens < 1000000:
        # 12.3k
        k = tokens / 1000
        if k == int(k):
            return f"{int(k)}k"
        else:
            return f"{k:.1f}k"
    else:
        # 2M345k
        m = tokens // 1000000
        remaining = (tokens % 1000000) // 1000
        if remaining == 0:
            return f"{m}M"
        else:
            return f"{m}M{remaining}k"


def get_current_git_branch(path: Path | None = None) -> str | None:
    """Get current git branch name, return None if not in a git repository"""
    if path is None:
        path = Path.cwd()

    try:
        # Check if in git repository
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )

        if git_dir.returncode != 0:
            return None

        # Get current branch name
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )

        if result.returncode == 0:
            branch = result.stdout.strip()
            return branch if branch else None

        # Fallback: get HEAD reference
        head_file = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=2,
        )

        if head_file.returncode == 0:
            branch = head_file.stdout.strip()
            return branch if branch and branch != "HEAD" else None

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        pass

    return None


def show_path_with_tilde(path: Path | None = None):
    if path is None:
        path = Path.cwd()

    try:
        relative_path = path.relative_to(Path.home())
        return f"~/{relative_path}"
    except ValueError:
        return str(path)
