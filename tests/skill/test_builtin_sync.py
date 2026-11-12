import json
import multiprocessing
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest
from typer.testing import CliRunner

from klaude_code.cli.main import app
from klaude_code.skill import builtin_sync


def _skill(root: Path, text: str, name: str = "klaude-config") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(text)
    return directory


def _sync_process(source: Path, dest: Path, entered: Event, release: Event) -> None:
    write = builtin_sync._write_manifest

    def wait_before_write(path: Path, manifest: dict[str, str]) -> None:
        entered.set()
        assert release.wait(10)
        write(path, manifest)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(builtin_sync, "_write_manifest", wait_before_write)
        builtin_sync._sync(source, dest)


def test_install_update_and_preserve_local_changes(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    skill = _skill(source, "one")
    _skill(source, "other", "klaude-session-logs")
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "SKILL.md").read_text() == "one"
    manifest = json.loads((dest / builtin_sync._MANIFEST).read_text())
    assert set(manifest) == {"klaude-config", "klaude-session-logs"}

    (skill / "SKILL.md").write_text("two")
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "SKILL.md").read_text() == "two"

    (dest / "klaude-config" / "extra").write_text("user data")
    (skill / "SKILL.md").write_text("three")
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "SKILL.md").read_text() == "two"
    assert (dest / "klaude-config" / "extra").read_text() == "user data"


def test_deleted_and_existing_skills_are_not_overwritten(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "bundled")
    _skill(source, "bundled", "klaude-session-logs")
    existing = _skill(dest, "user", "klaude-session-logs")
    builtin_sync._sync(source, dest)
    (dest / "klaude-config" / "SKILL.md").unlink()
    (dest / "klaude-config").rmdir()
    builtin_sync._sync(source, dest)
    assert not (dest / "klaude-config").exists()
    assert (existing / "SKILL.md").read_text() == "user"


def test_update_restores_backup_on_manifest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    skill = _skill(source, "old")
    builtin_sync._sync(source, dest)
    original_manifest = (dest / builtin_sync._MANIFEST).read_text()
    (skill / "SKILL.md").write_text("new")

    def fail(*args: object) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(builtin_sync, "_write_manifest", fail)
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "SKILL.md").read_text() == "old"
    assert (dest / builtin_sync._MANIFEST).read_text() == original_manifest


def test_install_rolls_back_on_manifest_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "bundled")
    existing = _skill(dest, "user", "klaude-session-logs")
    original = builtin_sync._write_manifest

    def fail(*args: object) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(builtin_sync, "_write_manifest", fail)
    builtin_sync._sync(source, dest)
    assert not (dest / "klaude-config").exists()
    assert (existing / "SKILL.md").read_text() == "user"
    monkeypatch.setattr(builtin_sync, "_write_manifest", original)
    builtin_sync._sync(source, dest)
    assert "klaude-config" in json.loads((dest / builtin_sync._MANIFEST).read_text())


def test_install_failure_preserves_user_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "bundled")

    def fail(*args: object) -> None:
        (dest / "klaude-config" / "user-file").write_text("user data")
        raise OSError("write failed")

    monkeypatch.setattr(builtin_sync, "_write_manifest", fail)
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "user-file").read_text() == "user data"


def test_concurrent_sync_serializes_manifest_updates(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "one")
    _skill(source, "two", "klaude-session-logs")
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    first = ctx.Process(target=_sync_process, args=(source, dest, entered, release))
    second = ctx.Process(target=builtin_sync._sync, args=(source, dest))
    first.start()
    try:
        assert entered.wait(10)
        second.start()
        second.join(0.5)
        assert second.is_alive()
    finally:
        release.set()
        first.join(10)
        if second.pid is not None:
            second.join(10)
    assert first.exitcode == second.exitcode == 0
    assert set(json.loads((dest / builtin_sync._MANIFEST).read_text())) == set(builtin_sync._NAMES)


def test_restore_interrupted_update(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "old")
    builtin_sync._sync(source, dest)
    temp = dest / ".builtin-skill-interrupted"
    temp.mkdir()
    (dest / "klaude-config").rename(temp / "backup-klaude-config")
    builtin_sync._sync(source, dest)
    assert (dest / "klaude-config" / "SKILL.md").read_text() == "old"


def test_unchanged_skills_are_not_copied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "bundled")
    builtin_sync._sync(source, dest)

    def fail(*args: object) -> None:
        raise AssertionError("unchanged skill was copied")

    monkeypatch.setattr(builtin_sync, "_copy_resource", fail)
    builtin_sync._sync(source, dest)


def test_invalid_manifest_and_symlink_are_left_alone(tmp_path: Path) -> None:
    source, dest = tmp_path / "source", tmp_path / "dest"
    _skill(source, "bundled")
    dest.mkdir()
    manifest = dest / builtin_sync._MANIFEST
    manifest.write_text("invalid")
    with pytest.raises(ValueError):
        builtin_sync._sync(source, dest)
    assert manifest.read_text() == "invalid"
    manifest.unlink()
    external = _skill(tmp_path / "external", "user")
    (dest / "klaude-config").symlink_to(external, target_is_directory=True)
    builtin_sync._sync(source, dest)
    assert (external / "SKILL.md").read_text() == "user"


def test_cli_invokes_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(builtin_sync, "sync_builtin_skills", lambda: calls.append(True))
    assert CliRunner().invoke(app, ["--help"]).exit_code == 0
    assert calls == [True]
