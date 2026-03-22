from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import klaude_code.update as update


def test_get_startup_update_summary_without_state_starts_background_check(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    assert update.get_startup_update_summary() is None
    assert started["value"] is True


def test_persist_current_update_info_writes_state_file(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home

    monkeypatch.setattr(
        update,
        "_fetch_version_info",
        lambda: update.VersionInfo(
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_INDEX,
        ),
    )

    update._persist_current_update_info()

    path = Path.home() / ".klaude" / update.UPDATE_STATE_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["installed"] == "1.0.0"
    assert payload["latest"] == "1.1.0"
    assert payload["update_available"] is True
    assert payload["install_kind"] == update.INSTALL_KIND_INDEX


def test_get_startup_update_summary_returns_message_from_persisted_state(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    update._write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_LOCAL,
        )
    )

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    summary = update.get_startup_update_summary()
    assert summary is not None
    assert summary.level == "warn"
    assert summary.message == (
        "PyPI 1.1.0 available. Current 1.0.0 (local path install); "
        "run `klaude upgrade` from a clean local checkout."
    )
    assert started["value"] is False


def test_get_startup_update_summary_refreshes_stale_state_in_background(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    update._write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time() - update.CHECK_INTERVAL_SECONDS - 1,
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_EDITABLE,
        )
    )

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    summary = update.get_startup_update_summary()
    assert summary is not None
    assert "editable install" in summary.message
    assert started["value"] is True
