"""Drag-and-drop / paste helpers for the REPL input.

Terminals typically implement drag-and-drop as a bracketed paste of either:
- A file URL (e.g. "file:///Users/me/foo.txt")
- A shell-escaped path (e.g. "/Users/me/My\\ File.txt")

We convert these into the input formats that Klaude already supports:
- Regular files/dirs -> @path (quoted when needed)
- Image files -> [image <path>] markers (resolved to ImageURLPart on submit)
"""

from __future__ import annotations

import contextlib
import re
import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse

from klaude_code.tui.input.images import format_image_marker, is_image_file

_FILE_URI_RE = re.compile(r"file://\S+")


def _format_at_token(path_str: str) -> str:
    """Format a file path for the @ reader, quoting when whitespace exists."""

    if any(ch.isspace() for ch in path_str):
        return f'@"{path_str}"'
    return f"@{path_str}"


def _normalize_path_for_at(path: Path, *, cwd: Path) -> str:
    """Return a stable, display-friendly path string for @ references."""

    # Use absolute() instead of resolve() to avoid expanding symlinks.
    # On macOS, /var -> /private/var, and users expect /var paths to stay as /var.
    try:
        resolved = path.absolute()
    except OSError:
        resolved = path

    cwd_resolved = cwd
    with contextlib.suppress(OSError):
        cwd_resolved = cwd.absolute()

    as_dir = False
    try:
        as_dir = resolved.exists() and resolved.is_dir()
    except OSError:
        as_dir = False

    # Prefer relative paths under CWD to match completer output.
    candidate: str
    try:
        rel = resolved.relative_to(cwd_resolved)
        candidate = rel.as_posix()
    except ValueError:
        candidate = resolved.as_posix()

    if as_dir and candidate and not candidate.endswith("/"):
        candidate += "/"
    return candidate


def _file_uri_to_path(uri: str) -> Path | None:
    """Parse a file:// URI to a filesystem path."""

    try:
        parsed = urlparse(uri)
    except Exception:
        return None

    if parsed.scheme != "file":
        return None

    # Common forms:
    # - file:///Users/me/foo.txt
    # - file://localhost/Users/me/foo.txt
    # - file:///C:/Users/me/foo.txt (Windows)
    raw_path = unquote(parsed.path or "")
    if not raw_path:
        return None

    if re.match(r"^/[A-Za-z]:/", raw_path):
        # Windows drive letter URIs often include an extra leading slash.
        raw_path = raw_path[1:]

    return Path(raw_path)


def _replace_file_uris(
    text: str,
    *,
    cwd: Path,
) -> tuple[str, bool]:
    """Replace all file://... occurrences in text.

    Returns (new_text, changed).
    """

    changed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed
        uri = match.group(0)

        # Strip trailing punctuation that is very likely not part of the URI.
        trail = ""
        while uri and uri[-1] in ")],.;:!?":
            trail = uri[-1] + trail
            uri = uri[:-1]

        path = _file_uri_to_path(uri)
        if path is None:
            return match.group(0)

        try:
            is_image = path.exists() and path.is_file() and is_image_file(path)
        except OSError:
            is_image = False

        if is_image:
            changed = True
            return format_image_marker(_normalize_path_for_at(path, cwd=cwd)) + trail

        token = _format_at_token(_normalize_path_for_at(path, cwd=cwd))
        changed = True
        return token + trail

    out = _FILE_URI_RE.sub(_replace, text)
    return out, changed


def _expand_path(token: str) -> Path | None:
    """Expand a shell token into a path, or None when it cannot be resolved.

    `Path.expanduser()` raises RuntimeError, not OSError, for a `~` prefix it
    cannot resolve (e.g. `~nosuchuser`); a paste must never break the prompt.
    """

    try:
        return Path(token).expanduser()
    except (OSError, RuntimeError, ValueError):
        return None


def _existing_paths(text: str) -> list[Path] | None:
    """Return the pasted tokens as paths, or None when text is not a path list."""

    stripped = text.strip()
    if not stripped:
        return None

    # Avoid converting when the paste already contains our input syntax.
    if "@" in stripped or "[image " in stripped:
        return None

    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return None

    if not tokens:
        return None

    # Heuristic: every token must exist on disk.
    paths: list[Path] = []
    for tok in tokens:
        path = _expand_path(tok)
        if path is None:
            return None
        try:
            if not path.exists():
                return None
        except OSError:
            return None
        paths.append(path)

    return paths


def _convert_path_list(text: str, *, cwd: Path) -> str | None:
    """Convert a plain list of existing paths into @ tokens, or None."""

    paths = _existing_paths(text)
    if paths is None:
        return None

    converted: list[str] = []
    for path in paths:
        try:
            is_image = path.is_file() and is_image_file(path)
        except OSError:
            is_image = False

        normalized = _normalize_path_for_at(path, cwd=cwd)
        if is_image:
            converted.append(format_image_marker(normalized))
        else:
            converted.append(_format_at_token(normalized))

    return " ".join(converted)


def convert_dropped_text(
    text: str,
    *,
    cwd: Path,
    allow_path_lists: bool = False,
) -> str:
    """Convert drag-and-drop text into @ tokens and/or image markers.

    `file://` URIs are always converted. Terminals that drop a file as an
    escaped plain path instead are handled by `allow_path_lists`, which the
    bracketed-paste handler sets: that is the moment a drag-and-drop lands, so
    rewriting the buffer is intended. Submit-time fallbacks keep it off, so
    they never rewrite what the user typed or pasted by hand.

    A converted payload loses its trailing newline: the caller appends the
    single separating space, which the newline would otherwise suppress.
    """

    out, changed = _replace_file_uris(text, cwd=cwd)

    if not changed and allow_path_lists:
        path_list = _convert_path_list(text, cwd=cwd)
        if path_list is not None:
            out, changed = path_list, True

    if not changed:
        return out

    return out.removesuffix("\n")
