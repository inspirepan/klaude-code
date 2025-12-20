"""System skills management - install built-in skills to user directory.

This module handles extracting bundled skills from the package to ~/.klaude/skills/.system/
on application startup. It uses a fingerprint mechanism to avoid unnecessary re-extraction.
"""

import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from klaude_code.trace import log_debug

# Marker file name for tracking installed skills version
SYSTEM_SKILLS_MARKER_FILENAME = ".klaude-system-skills.marker"

# Salt for fingerprint calculation (increment to force re-extraction)
SYSTEM_SKILLS_MARKER_SALT = "v1"


def get_system_skills_dir() -> Path:
    """Get the system skills installation directory.

    Returns:
        Path to ~/.klaude/skills/.system/
    """
    return Path.home() / ".klaude" / "skills" / ".system"


def _calculate_fingerprint(assets_dir: Path) -> str:
    """Calculate a fingerprint hash for the embedded skills assets.

    The fingerprint is based on all file paths and their contents.

    Args:
        assets_dir: Path to the assets directory

    Returns:
        Hex string of the hash
    """
    hasher = hashlib.sha256()
    hasher.update(SYSTEM_SKILLS_MARKER_SALT.encode())

    if not assets_dir.exists():
        return hasher.hexdigest()

    # Sort entries for consistent ordering
    for entry in sorted(assets_dir.rglob("*")):
        if entry.is_file():
            # Hash the relative path
            rel_path = entry.relative_to(assets_dir)
            hasher.update(str(rel_path).encode())
            # Hash the file contents
            hasher.update(entry.read_bytes())

    return hasher.hexdigest()


def _read_marker(marker_path: Path) -> str | None:
    """Read the fingerprint from the marker file.

    Args:
        marker_path: Path to the marker file

    Returns:
        The stored fingerprint, or None if the file doesn't exist or is invalid
    """
    try:
        if marker_path.exists():
            return marker_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return None


def _write_marker(marker_path: Path, fingerprint: str) -> None:
    """Write the fingerprint to the marker file.

    Args:
        marker_path: Path to the marker file
        fingerprint: The fingerprint to store
    """
    marker_path.write_text(f"{fingerprint}\n", encoding="utf-8")


@contextmanager
def _with_embedded_assets_dir() -> Iterator[Path | None]:
    """Resolve the embedded assets directory as a real filesystem path.

    Uses `importlib.resources.as_file()` so it works for both normal installs
    and zipimport-style environments.
    """
    try:
        assets_ref = resources.files("klaude_code.skill").joinpath("assets")
        with resources.as_file(assets_ref) as assets_path:
            p = Path(assets_path)
            yield p if p.exists() else None
            return
    except (TypeError, AttributeError, ImportError, FileNotFoundError, OSError):
        pass

    try:
        module_dir = Path(__file__).parent
        assets_path = module_dir / "assets"
        yield assets_path if assets_path.exists() else None
    except (TypeError, NameError, OSError):
        yield None


def install_system_skills() -> bool:
    """Install system skills from the embedded assets to the user directory.

    This function:
    1. Calculates a fingerprint of the embedded assets
    2. Checks if the installed skills match (via marker file)
    3. If they don't match, clears and re-extracts the skills

    Returns:
        True if skills were installed/updated, False if already up-to-date
    """
    dest_dir = get_system_skills_dir()
    marker_path = dest_dir / SYSTEM_SKILLS_MARKER_FILENAME

    with _with_embedded_assets_dir() as assets_path:
        if assets_path is None or not assets_path.exists():
            log_debug("No embedded system skills found")
            return False

        # Calculate fingerprint of embedded assets
        expected_fingerprint = _calculate_fingerprint(assets_path)

        # Check if already installed with matching fingerprint
        current_fingerprint = _read_marker(marker_path)
        if current_fingerprint == expected_fingerprint and dest_dir.exists():
            log_debug("System skills already up-to-date")
            return False

        log_debug(f"Installing system skills to {dest_dir}")

        # Clear existing installation
        if dest_dir.exists():
            try:
                shutil.rmtree(dest_dir)
            except OSError as e:
                log_debug(f"Failed to clear existing system skills: {e}")
                return False

        # Create destination directory
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy all skill directories from assets
        try:
            for item in assets_path.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    dest_skill_dir = dest_dir / item.name
                    shutil.copytree(item, dest_skill_dir)
                    log_debug(f"Installed system skill: {item.name}")
        except OSError as e:
            log_debug(f"Failed to copy system skills: {e}")
            return False

        # Write marker file
        try:
            _write_marker(marker_path, expected_fingerprint)
        except OSError as e:
            log_debug(f"Failed to write marker file: {e}")
            # Installation succeeded, just marker failed

        log_debug("System skills installation complete")
        return True


def get_installed_system_skills() -> list[Path]:
    """Get list of installed system skill directories.

    Returns:
        List of paths to installed skill directories
    """
    dest_dir = get_system_skills_dir()
    if not dest_dir.exists():
        return []

    skills: list[Path] = []
    for item in dest_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            skill_file = item / "SKILL.md"
            if skill_file.exists():
                skills.append(item)

    return skills
