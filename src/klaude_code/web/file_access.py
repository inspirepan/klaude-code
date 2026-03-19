from __future__ import annotations

from pathlib import Path

TMP_DIR = Path("/tmp").resolve()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _is_session_images_path(path: Path, home_dir: Path) -> bool:
    projects_root = (home_dir / ".klaude" / "projects").resolve()
    if not _is_relative_to(path, projects_root):
        return False
    relative = path.relative_to(projects_root)
    if len(relative.parts) < 4:
        return False
    return relative.parts[1] == "sessions" and relative.parts[3] == "images"


def validate_file_access(raw_path: str, *, work_dir: Path, home_dir: Path) -> tuple[int, Path | None]:
    """Validate file access path.

    Returns:
        Tuple of (status_code, resolved_path). status_code is 200 when allowed.
    """

    requested = Path(raw_path)
    if not requested.is_absolute():
        return 400, None
    if ".." in requested.parts:
        return 403, None

    resolved = requested.resolve(strict=False)
    work_dir_resolved = work_dir.resolve()

    allowed = (
        _is_relative_to(resolved, work_dir_resolved)
        or _is_relative_to(resolved, TMP_DIR)
        or _is_session_images_path(resolved, home_dir)
    )
    if not allowed:
        return 403, None

    if not resolved.exists() or not resolved.is_file():
        return 404, None
    return 200, resolved
