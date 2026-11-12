"""Synchronize bundled skills without overwriting user changes."""

import hashlib
import json
import logging
import os
import shutil
import tempfile
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from filelock import FileLock

_NAMES = ("klaude-config", "klaude-session-logs")
_MANIFEST = ".builtin-manifest.json"
_logger = logging.getLogger(__name__)


def _copy_resource(source: Traversable, destination: Path) -> None:
    destination.mkdir()
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource(child, target)
        elif child.is_file():
            target.write_bytes(child.read_bytes())
        else:
            raise ValueError(f"Unsupported resource: {child}")


def _directory_hash(directory: Traversable) -> str:
    digest = hashlib.sha256()
    entries: list[tuple[str, Traversable]] = []

    def collect(parent: Traversable, prefix: str = "") -> None:
        for child in parent.iterdir():
            relative = f"{prefix}{child.name}"
            entries.append((relative, child))
            if child.is_dir() and not (isinstance(child, Path) and child.is_symlink()):
                collect(child, relative + "/")

    collect(directory)
    for name, path in sorted(entries, key=lambda entry: entry[0]):
        if isinstance(path, Path) and path.is_symlink():
            raise ValueError(f"Symbolic link in skill: {path}")
        relative = name.encode()
        if path.is_dir():
            digest.update(b"D" + len(relative).to_bytes(8, "big") + relative)
        elif path.is_file():
            data = path.read_bytes()
            digest.update(b"F" + len(relative).to_bytes(8, "big") + relative + len(data).to_bytes(8, "big") + data)
        else:
            raise ValueError(f"Unsupported file in skill: {path}")
    return digest.hexdigest()


def _write_manifest(path: Path, manifest: dict[str, str]) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            json.dump(manifest, temp, sort_keys=True)
            temp.write("\n")
            temp.close()
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)


def sync_builtin_skills() -> None:
    source = files("klaude_code.skill").joinpath("builtin_skills")
    if not source.is_dir():
        return
    try:
        _sync(source, Path.home() / ".klaude" / "skills")
    except (OSError, ValueError) as exc:
        _logger.warning("Could not synchronize bundled skills: %s", exc)


def _sync(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    lock_path = destination / ".builtin-sync.lock"
    if lock_path.is_symlink() or (lock_path.exists() and (not lock_path.is_file() or lock_path.stat().st_size)):
        raise ValueError("Invalid skill synchronization lock")
    with FileLock(lock_path):
        _sync_locked(source, destination)


def _sync_locked(source: Traversable, destination: Path) -> None:
    manifest_path = destination / _MANIFEST
    if manifest_path.is_symlink():
        raise ValueError("Skill manifest is a symbolic link")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in manifest.items()
        ):
            raise ValueError("Invalid skill manifest")
    else:
        manifest = {}

    for temp_dir in destination.glob(".builtin-skill-*"):
        if temp_dir.is_symlink() or not temp_dir.is_dir():
            continue
        for name in _NAMES:
            backup = temp_dir / ("backup-" + name)
            target = destination / name
            if (
                name in manifest
                and not target.exists()
                and not target.is_symlink()
                and backup.is_dir()
                and not backup.is_symlink()
                and _directory_hash(backup) == manifest[name]
            ):
                backup.rename(target)

    for name in _NAMES:
        resource = source.joinpath(name)
        if not resource.is_dir():
            continue
        target = destination / name
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            continue
        previous = manifest.get(name)
        if not target.exists() and previous is not None:
            continue
        try:
            new_hash = _directory_hash(resource)
            if target.exists():
                current_hash = _directory_hash(target)
                if previous is None or current_hash != previous or current_hash == new_hash:
                    continue
            temp_dir = Path(tempfile.mkdtemp(prefix=".builtin-skill-", dir=destination))
            try:
                staged = temp_dir / "new"
                _copy_resource(resource, staged)
                new_hash = _directory_hash(staged)
                if target.exists():
                    current_hash = _directory_hash(target)
                    if previous is None or current_hash != previous or current_hash == new_hash:
                        continue
                    backup = temp_dir / ("backup-" + name)
                    target.rename(backup)
                    try:
                        staged.rename(target)
                        _write_manifest(manifest_path, {**manifest, name: new_hash})
                    except Exception:
                        if target.exists():
                            target.rename(staged)
                        backup.rename(target)
                        raise
                else:
                    installed_stat = staged.stat()
                    staged.rename(target)
                    try:
                        _write_manifest(manifest_path, {**manifest, name: new_hash})
                    except Exception:
                        if (
                            not target.is_symlink()
                            and target.exists()
                            and target.stat().st_ino == installed_stat.st_ino
                            and _directory_hash(target) == new_hash
                        ):
                            target.rename(staged)
                        raise
                manifest[name] = new_hash
            finally:
                # Preserve the backup if restoration itself failed.
                if not (temp_dir / ("backup-" + name)).exists() or (target.exists() and manifest.get(name) == new_hash):
                    shutil.rmtree(temp_dir)
        except (OSError, ValueError) as exc:
            _logger.warning("Could not synchronize bundled skill %s: %s", name, exc)
