from __future__ import annotations

import time
from pathlib import Path

from klaude_code.core.clipboard_manifest import (
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

