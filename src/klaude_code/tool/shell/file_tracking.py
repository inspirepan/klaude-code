"""Best-effort file-tracker updates inferred from a shell command.

The Bash tool cannot know which files a command touched, so it guesses from the argv of a
few well-known tools (``cat`` / ``sed`` / ``mv``). Complex shell scripts are deliberately
not interpreted: a miss just means the tracker keeps a slightly stale entry, which is
recoverable, whereas guessing wrongly would report edits that never happened.

This lives outside ``BashTool.call_with_args`` so the argv heuristics can be exercised
without spawning a subprocess.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shlex
from pathlib import Path

from klaude_code.protocol.models import FileStatus
from klaude_code.tool.core.context import FileTracker

# Binary formats are hashed as raw bytes; everything else is hashed line by line as UTF-8 so
# the digest matches the way the read/edit tools normalize text content.
_BINARY_HASH_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})


def hash_file_content_sha256(file_path: str) -> str | None:
    """Return the content digest for `file_path`, or None when it cannot be read."""
    try:
        if Path(file_path).suffix.lower() in _BINARY_HASH_SUFFIXES:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        hasher = hashlib.sha256()
        with open(file_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                hasher.update(line.encode("utf-8"))
        return hasher.hexdigest()
    except (FileNotFoundError, IsADirectoryError, OSError, PermissionError, UnicodeDecodeError):
        return None


def resolve_in_dir(base_dir: str, path: str) -> str:
    """Resolve `path` against `base_dir`, leaving already-absolute paths alone."""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base_dir, path))


class ShellFileTracker:
    """Applies best-effort tracker updates for files a shell command likely touched."""

    def __init__(self, file_tracker: FileTracker, work_dir: Path) -> None:
        self._file_tracker = file_tracker
        self._work_dir = work_dir

    def update_from_command(self, command: str) -> None:
        """Inspect `command` and record any files it probably read or wrote."""
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            return
        if not argv:
            return

        # Handle common patterns like: cd subdir && cat file
        base_dir = str(self._work_dir)
        while len(argv) >= 4 and argv[0] == "cd" and argv[2] == "&&":
            dest = argv[1]
            if dest != "-":
                base_dir = resolve_in_dir(base_dir, dest)
            argv = argv[3:]
            if not argv:
                return

        cmd0 = argv[0]
        if cmd0 == "cat":
            paths = [a for a in argv[1:] if a and not a.startswith("-") and a != "-"]
            self.track_files_read(paths, base_dir=base_dir)
            return

        if cmd0 == "sed":
            # Support: sed [-i ...] 's/old/new/' file1 [file2 ...]
            # and: sed -n 'Np' file
            saw_script = False
            file_paths: list[str] = []
            for a in argv[1:]:
                if not a:
                    continue
                if a == "--":
                    continue
                if a.startswith("-") and not saw_script:
                    continue
                if not saw_script and (a.startswith("s/") or a.startswith("s|") or a.endswith("p")):
                    saw_script = True
                    continue
                if saw_script and not a.startswith("-"):
                    file_paths.append(a)

            if file_paths:
                self.track_files_written(file_paths, base_dir=base_dir)
            return

        if cmd0 == "mv":
            # Support: mv [opts] src... dest
            operands: list[str] = []
            end_of_opts = False
            for a in argv[1:]:
                if not end_of_opts and a == "--":
                    end_of_opts = True
                    continue
                if not end_of_opts and a.startswith("-"):
                    continue
                operands.append(a)
            if len(operands) < 2:
                return
            self.track_mv(operands[:-1], operands[-1], base_dir=base_dir)
            return

    def track_files_read(self, file_paths: list[str], *, base_dir: str) -> None:
        for p in file_paths:
            abs_path = resolve_in_dir(base_dir, p)
            if not os.path.exists(abs_path) or os.path.isdir(abs_path):
                continue
            sha = hash_file_content_sha256(abs_path)
            if sha is None:
                continue
            self._record(abs_path, sha, self._file_tracker.get(abs_path))

    def track_files_written(self, file_paths: list[str], *, base_dir: str) -> None:
        # Same as read tracking, but intentionally kept separate for clarity.
        self.track_files_read(file_paths, base_dir=base_dir)

    def track_mv(self, src_paths: list[str], dest_path: str, *, base_dir: str) -> None:
        abs_dest = resolve_in_dir(base_dir, dest_path)
        dest_is_dir = os.path.isdir(abs_dest)

        for src in src_paths:
            abs_src = resolve_in_dir(base_dir, src)
            abs_new = os.path.join(abs_dest, os.path.basename(abs_src)) if dest_is_dir else abs_dest

            # Remove old entry if present.
            existing = self._file_tracker.pop(abs_src, None)

            if not os.path.exists(abs_new) or os.path.isdir(abs_new):
                continue

            sha = hash_file_content_sha256(abs_new)
            if sha is None:
                continue
            self._record(abs_new, sha, existing)

    def _record(self, abs_path: str, sha: str, existing: FileStatus | None) -> None:
        """Store a tracker entry, carrying over classification flags from `existing`."""
        with contextlib.suppress(Exception):
            self._file_tracker[abs_path] = FileStatus(
                mtime=Path(abs_path).stat().st_mtime,
                content_sha256=sha,
                is_memory=existing.is_memory if existing else False,
                is_skill=existing.is_skill if existing else False,
                skill_attachment_source=None,
                is_directory=existing.is_directory if existing else False,
            )
