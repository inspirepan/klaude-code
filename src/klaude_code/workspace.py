"""Workspace path resolution.

One server process hosts sessions rooted in different directories, so the
process CWD is meaningless for session work. Every relative path that comes
from user input (@file references) or model tool arguments must be resolved
against the session's ``work_dir`` through these helpers — never through
``Path.cwd()`` / ``os.getcwd()`` / ``os.path.abspath``.
"""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceEscapeError(ValueError):
    """A relative path resolved to a location outside the workspace root."""


def resolve_workspace_path(raw: str | os.PathLike[str], work_dir: Path, *, strict: bool = False) -> Path:
    """Resolve ``raw`` against ``work_dir``.

    Absolute paths (after ``~`` expansion) pass through untouched; relative
    paths are joined onto ``work_dir``. The result is fully resolved
    (symlinks included). With ``strict=True``, a relative path whose resolved
    location escapes ``work_dir`` raises :class:`WorkspaceEscapeError`;
    absolute paths are never subject to the containment check.
    """

    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()

    resolved = (work_dir / expanded).resolve()
    if strict and not resolved.is_relative_to(work_dir.resolve()):
        raise WorkspaceEscapeError(f"Path escapes workspace: {raw}")
    return resolved
