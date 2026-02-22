from __future__ import annotations

from _pytest.monkeypatch import MonkeyPatch

import klaude_code.update as update


def _reset_auto_upgrade_state(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(update, "_auto_upgrade_attempted", False)
    monkeypatch.setattr(update, "_auto_upgrade_in_progress", False)
    monkeypatch.setattr(update, "_auto_upgrade_succeeded", False)
    monkeypatch.setattr(update, "_auto_upgrade_failed", False)
    monkeypatch.setattr(update, "_auto_upgrade_target_version", None)


def test_get_update_message_index_triggers_background_upgrade(monkeypatch: MonkeyPatch) -> None:
    _reset_auto_upgrade_state(monkeypatch)

    info = update.VersionInfo(
        installed="1.0.0",
        latest="1.1.0",
        update_available=True,
        install_kind=update.INSTALL_KIND_INDEX,
    )
    monkeypatch.setattr(update, "check_for_updates", lambda: info)

    def _fake_start_auto_upgrade(start_info: update.VersionInfo) -> None:
        assert start_info.latest == "1.1.0"
        update._auto_upgrade_in_progress = True  # type: ignore
        update._auto_upgrade_target_version = "1.1.0"  # type: ignore

    monkeypatch.setattr(update, "_start_auto_upgrade_if_needed", _fake_start_auto_upgrade)

    message = update.get_update_message()
    assert message is not None
    assert "Updating in background" in message
    assert "next launch" in message


def test_get_update_message_shows_background_upgrade_completed(monkeypatch: MonkeyPatch) -> None:
    _reset_auto_upgrade_state(monkeypatch)
    monkeypatch.setattr(update, "_auto_upgrade_succeeded", True)  # type: ignore
    monkeypatch.setattr(update, "_auto_upgrade_target_version", "1.1.0")  # type: ignore
    monkeypatch.setattr(update, "check_for_updates", lambda: None)

    message = update.get_update_message()
    assert message == "Background update to 1.1.0 completed. Restart `klaude` to use it."


def test_get_update_message_shows_auto_upgrade_failure(monkeypatch: MonkeyPatch) -> None:
    _reset_auto_upgrade_state(monkeypatch)
    monkeypatch.setattr(update, "_auto_upgrade_failed", True)  # type: ignore
    monkeypatch.setattr(update, "_auto_upgrade_attempted", True)  # type: ignore

    info = update.VersionInfo(
        installed="1.0.0",
        latest="1.1.0",
        update_available=True,
        install_kind=update.INSTALL_KIND_INDEX,
    )
    monkeypatch.setattr(update, "check_for_updates", lambda: info)
    monkeypatch.setattr(update, "_start_auto_upgrade_if_needed", lambda _info: None)  # type: ignore

    message = update.get_update_message()
    assert message == "New version available: 1.1.0. Auto-update failed; run `klaude upgrade`."


def test_get_update_message_editable_skips_background_upgrade(monkeypatch: MonkeyPatch) -> None:
    _reset_auto_upgrade_state(monkeypatch)

    info = update.VersionInfo(
        installed="1.0.0",
        latest="1.1.0",
        update_available=True,
        install_kind=update.INSTALL_KIND_EDITABLE,
    )
    monkeypatch.setattr(update, "check_for_updates", lambda: info)

    started = {"value": False}

    def _fake_start_auto_upgrade(_info: update.VersionInfo) -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_auto_upgrade_if_needed", _fake_start_auto_upgrade)

    message = update.get_update_message()
    assert started["value"] is False
    assert message == "PyPI 1.1.0 available. Local editable install detected; pull latest source."
