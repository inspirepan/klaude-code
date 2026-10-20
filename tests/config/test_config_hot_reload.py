"""Tests for picking up config edits without restarting the process."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
import yaml

import klaude_code.config.config as _config_module
import klaude_code.config.loader as _loader
from klaude_code.config import ConfigReload, config_revision, load_config
from klaude_code.config.loader import ConfigWatcher, check_config_change, start_config_watcher


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the loader at a fresh user config file for this test."""
    path = tmp_path / "klaude-config.yaml"
    monkeypatch.setattr(_config_module, "config_path", path)
    load_config.cache_clear()
    return path


def _write(path: Path, main_model: str) -> None:
    path.write_text(yaml.dump({"main_model": main_model}), encoding="utf-8")


class TestLoadConfigPicksUpDiskChanges:
    def test_edit_is_visible_without_cache_clear(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        assert load_config().main_model == "first-model"

        _write(config_file, "second-model")

        assert load_config().main_model == "second-model"

    def test_new_file_is_visible(self, config_file: Path) -> None:
        assert load_config().main_model != "created-later"

        _write(config_file, "created-later")

        assert load_config().main_model == "created-later"

    def test_deleted_file_falls_back_to_builtin(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        loaded = load_config()
        assert loaded.main_model == "first-model"

        config_file.unlink()

        assert load_config() is not loaded
        assert load_config().main_model != "first-model"

    def test_unchanged_files_reuse_the_cached_instance(self, config_file: Path) -> None:
        """Every caller mutates the returned Config, so it must stay one object."""
        _write(config_file, "first-model")

        assert load_config() is load_config()

    def test_auth_file_edit_is_visible(self, config_file: Path, isolated_home: Path) -> None:
        """klaude-auth.json resolves ${ENV_VAR} api_keys, so it is an input too."""
        _write(config_file, "first-model")
        loaded = load_config()
        assert loaded.main_model == "first-model"

        isolated_home.joinpath(".klaude").mkdir(parents=True, exist_ok=True)
        isolated_home.joinpath(".klaude", "klaude-auth.json").write_text(
            '{"env": {"ANTHROPIC_API_KEY": "sk-test"}}', encoding="utf-8"
        )

        assert load_config() is not loaded


class TestConfigRevision:
    def test_first_load_reports_a_revision(self, config_file: Path) -> None:
        load_config()

        assert config_revision() >= 1

    def test_revision_is_monotonic_across_edits(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()
        revisions = [config_revision()]

        for model in ("second-model", "third-model", "fourth-model"):
            _write(config_file, model)
            load_config()
            revisions.append(config_revision())

        assert revisions == sorted(revisions)
        assert revisions[-1] > revisions[0]

    def test_save_does_not_bump_the_revision(self, config_file: Path) -> None:
        """A process writing its own config must not look like an external edit."""
        _write(config_file, "first-model")
        config = load_config()
        assert config.main_model == "first-model"
        before = config_revision()

        config.main_model = "saved-model"
        asyncio.run(config.save())

        assert config_revision() == before
        # The in-memory instance survives: a rebuild would drop unsaved edits.
        assert load_config() is config
        assert load_config().main_model == "saved-model"

    def test_revision_moves_after_an_external_edit(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()
        before = config_revision()

        _write(config_file, "external-model")

        assert load_config().main_model == "external-model"
        assert config_revision() > before


class TestCheckConfigChange:
    def test_returns_none_when_nothing_changed(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()

        assert check_config_change() is None

    def test_reports_the_reload_with_a_summary(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()

        _write(config_file, "second-model")
        reload_event = check_config_change()

        assert isinstance(reload_event, ConfigReload)
        assert reload_event.revision == config_revision()
        assert "first-model" in reload_event.summary
        assert "second-model" in reload_event.summary

    def test_summary_names_changed_sub_agent_roles(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()

        config_file.write_text(
            yaml.dump({"main_model": "first-model", "sub_agent_models": {"finder": "haiku"}}),
            encoding="utf-8",
        )
        reload_event = check_config_change()

        assert reload_event is not None
        assert "finder" in reload_event.summary

    def test_a_reload_consumed_elsewhere_is_still_reported(self, config_file: Path) -> None:
        """The broadcast must not depend on who read the file first.

        Any runtime call (a socket handshake, the reload endpoint) can reload the
        config before the poll loop notices; that edit still has to be announced.
        """
        _write(config_file, "first-model")
        load_config()
        assert check_config_change() is None

        _write(config_file, "second-model")
        assert load_config().main_model == "second-model"

        reload_event = check_config_change()

        assert isinstance(reload_event, ConfigReload)
        assert "first-model" in reload_event.summary
        assert "second-model" in reload_event.summary
        # Reported once, not on every later poll.
        assert check_config_change() is None

    def test_consecutive_edits_report_from_what_clients_last_saw(self, config_file: Path) -> None:
        """Two edits before the next poll describe one change, from the client's state."""
        _write(config_file, "first-model")
        load_config()
        assert check_config_change() is None

        _write(config_file, "second-model")
        assert load_config().main_model == "second-model"
        _write(config_file, "third-model")
        assert load_config().main_model == "third-model"

        reload_event = check_config_change()

        assert reload_event is not None
        assert "first-model" in reload_event.summary
        assert "third-model" in reload_event.summary

    def test_summary_names_fast_and_compact_changes(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()
        assert check_config_change() is None

        config_file.write_text(
            yaml.dump({"main_model": "first-model", "fast_model": "haiku", "compact_model": "haiku"}),
            encoding="utf-8",
        )
        reload_event = check_config_change()

        assert reload_event is not None
        assert "fast model" in reload_event.summary
        assert "compact model" in reload_event.summary

    def test_repeated_invalid_edits_keep_reporting_nothing(self, config_file: Path) -> None:
        """A broken file must not make the poll loop raise or spin."""
        _write(config_file, "first-model")
        load_config()
        assert check_config_change() is None

        config_file.write_text("main_model: [unclosed", encoding="utf-8")

        assert check_config_change() is None
        # The failed load re-stamped the file, so a second poll reports nothing
        # instead of retrying the same broken read forever.
        assert check_config_change() is None

        # An explicit cache_clear (the reload endpoint, /manage-providers) leaves
        # no cached instance to compare against: the poll must survive that too.
        load_config.cache_clear()
        assert check_config_change() is None

        _write(config_file, "second-model")
        reload_event = check_config_change()

        assert reload_event is not None
        assert "first-model" in reload_event.summary
        assert "second-model" in reload_event.summary

    def test_invalid_edit_reports_nothing(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()

        config_file.write_text("main_model: [unclosed", encoding="utf-8")

        assert check_config_change() is None
        with pytest.raises(ValueError):
            load_config()

    def test_reload_survives_an_invalid_edit(self, config_file: Path) -> None:
        """A half-written file must not stop the next good edit from landing."""
        _write(config_file, "first-model")
        load_config()

        config_file.write_text("main_model: [unclosed", encoding="utf-8")
        assert check_config_change() is None

        _write(config_file, "second-model")

        assert load_config().main_model == "second-model"


class TestConfigWatcher:
    def test_calls_back_on_every_change(self, config_file: Path) -> None:
        _write(config_file, "first-model")
        load_config()

        seen: list[ConfigReload] = []
        done = threading.Event()

        def _on_reload(reload_event: ConfigReload) -> None:
            seen.append(reload_event)
            done.set()

        watcher = start_config_watcher(_on_reload, interval_s=0.01)
        try:
            _write(config_file, "second-model")
            assert done.wait(timeout=5.0), "watcher never reported the edit"
        finally:
            watcher.stop()

        assert [item.revision for item in seen] == [config_revision()]
        assert "second-model" in seen[0].summary

    def test_stop_joins_the_poll_loop(self) -> None:
        watcher = start_config_watcher(lambda _event: None, interval_s=0.01)
        thread = watcher._thread
        assert thread is not None and thread.is_alive()

        watcher.stop()

        assert not thread.is_alive()
        assert watcher._thread is None

    def test_callback_errors_do_not_kill_the_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The poll loop outlives a callback that raises (e.g. a dead event loop)."""
        calls = 0
        called = threading.Event()

        def _on_reload(_event: ConfigReload) -> None:
            nonlocal calls
            calls += 1
            called.set()
            raise RuntimeError("callback failed")

        monkeypatch.setattr(
            _loader,
            "check_config_change",
            lambda: ConfigReload(revision=1, summary="test"),
        )
        watcher = start_config_watcher(_on_reload, interval_s=0.01)
        try:
            assert called.wait(timeout=5.0)
            first = calls
            time.sleep(0.05)
            assert calls > first
        finally:
            watcher.stop()

    def test_watcher_errors_do_not_kill_the_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = 0
        called = threading.Event()

        def _failing_check() -> ConfigReload | None:
            nonlocal calls
            calls += 1
            called.set()
            raise RuntimeError("bad edit")

        monkeypatch.setattr(_loader, "check_config_change", _failing_check)
        watcher = ConfigWatcher(lambda _event: None, interval_s=0.01)
        watcher.start()
        try:
            assert called.wait(timeout=5.0)
            first = calls
            time.sleep(0.05)
            assert calls > first
        finally:
            watcher.stop()
