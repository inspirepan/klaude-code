from __future__ import annotations

import json
import time
from pathlib import Path

from codex_mini.core.clipboard_manifest import (
    ClipboardManifest,
    ClipboardManifestEntry,
    load_latest_clipboard_manifest,
    persist_clipboard_manifest,
)


def test_persist_and_load_manifest(tmp_path: Path) -> None:
    entry = ClipboardManifestEntry(tag="[Image #1]", path="/tmp/foo.png", saved_at_ts=time.time())
    manifest = ClipboardManifest(entries=[entry], created_at_ts=time.time(), source_id="pid-test")

    saved = persist_clipboard_manifest(manifest, storage_dir=tmp_path)

    assert saved is not None

    loaded = load_latest_clipboard_manifest(storage_dir=tmp_path)
    assert loaded is not None
    assert loaded.tag_map() == manifest.tag_map()
    assert loaded.source_id == "pid-test"


def test_loads_legacy_manifest_format(tmp_path: Path) -> None:
    legacy_payload = {"[Image #3]": "/tmp/legacy.png"}
    legacy_path = tmp_path / "last_clipboard_images.json"
    legacy_path.write_text(json.dumps(legacy_payload))

    loaded = load_latest_clipboard_manifest(storage_dir=tmp_path)

    assert loaded is not None
    assert loaded.tag_map() == legacy_payload
    assert loaded.source_id == "legacy"
