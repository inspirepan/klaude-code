import os
import subprocess
from pathlib import Path
from typing import cast

import pytest

from klaude_code.tui.input import images


@pytest.mark.parametrize("operation", ["check", "pngpaste", "osascript"])
@pytest.mark.parametrize("has_bundle_id", [False, True])
def test_macos_clipboard_helpers_do_not_inherit_app_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str, has_bundle_id: bool
) -> None:
    if has_bundle_id:
        monkeypatch.setenv("__CFBundleIdentifier", "com.mitchellh.ghostty")
    else:
        monkeypatch.delenv("__CFBundleIdentifier", raising=False)
    monkeypatch.setenv("KLAUDE_CLIPBOARD_TEST", "preserved")
    parent_env = os.environ.copy()
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert cmd[0] == ("pngpaste" if operation == "pngpaste" else "osascript")
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="true", stderr="")

    monkeypatch.setattr(images.subprocess, "run", fake_run)
    monkeypatch.setattr(images.shutil, "which", lambda _: "pngpaste" if operation == "pngpaste" else None)

    if operation == "check":
        assert images._has_clipboard_image_macos()
    else:
        dest_path = tmp_path / "clipboard.png"
        dest_path.write_bytes(b"image")
        assert images._grab_clipboard_image_macos(dest_path)

    env = cast(dict[str, str], captured["env"])
    assert env == {key: value for key, value in parent_env.items() if key != "__CFBundleIdentifier"}
    assert dict(os.environ) == parent_env
