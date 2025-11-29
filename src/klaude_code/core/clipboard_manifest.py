from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

CLIPBOARD_ROOT = Path.home() / ".klaude" / "clipboard"
CLIPBOARD_IMAGES_DIR = CLIPBOARD_ROOT / "images"
CLIPBOARD_MANIFESTS_DIR = CLIPBOARD_ROOT / "manifests"


@dataclass(slots=True)
class ClipboardManifestEntry:
    tag: str
    path: str
    saved_at_ts: float


@dataclass(slots=True)
class ClipboardManifest:
    entries: list[ClipboardManifestEntry]
    created_at_ts: float
    source_id: str | None = None

    def as_serializable(self) -> dict[str, Any]:
        return {
            "created_at_ts": self.created_at_ts,
            "source_id": self.source_id,
            "entries": [
                {
                    "tag": entry.tag,
                    "path": entry.path,
                    "saved_at_ts": entry.saved_at_ts,
                }
                for entry in self.entries
            ],
        }

    def tag_map(self) -> dict[str, str]:
        return {entry.tag: entry.path for entry in self.entries}


def _manifest_dir(storage_dir: Path | None = None) -> Path:
    if storage_dir:
        return storage_dir / "manifests"
    return CLIPBOARD_MANIFESTS_DIR


def persist_clipboard_manifest(
    manifest: ClipboardManifest,
    *,
    storage_dir: Path | None = None,
) -> Path | None:
    manifest_dir = _manifest_dir(storage_dir)
    timestamp_ms = int(manifest.created_at_ts * 1000)
    manifest_path = manifest_dir / f"manifest-{timestamp_ms}.json"
    try:
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest.as_serializable(), ensure_ascii=False, indent=2))
        return manifest_path
    except (OSError, ValueError, TypeError):
        return None


def load_latest_clipboard_manifest(*, storage_dir: Path | None = None) -> ClipboardManifest | None:
    manifest_dir = _manifest_dir(storage_dir)
    return _load_latest_manifest_file(manifest_dir)


def _load_latest_manifest_file(manifest_dir: Path) -> ClipboardManifest | None:
    if not manifest_dir.exists():
        return None
    manifest_files = sorted(
        manifest_dir.glob("manifest-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in manifest_files:
        try:
            payload = json.loads(path.read_text())
            manifest = _manifest_from_payload(payload)
            if manifest:
                return manifest
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return None


def _manifest_from_payload(payload: dict[str, Any]) -> ClipboardManifest | None:
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return None
    entries_data = cast(list[Any], entries_raw)
    entries: list[ClipboardManifestEntry] = []
    for entry_candidate in entries_data:
        if not isinstance(entry_candidate, dict):
            continue
        entry_data_dict = cast(dict[str, Any], entry_candidate)
        tag = entry_data_dict.get("tag")
        path = entry_data_dict.get("path")
        saved_at_raw = entry_data_dict.get("saved_at_ts")
        if not isinstance(tag, str) or not isinstance(path, str):
            continue
        saved_at_val = _to_float(saved_at_raw, time.time())
        entries.append(ClipboardManifestEntry(tag=tag, path=path, saved_at_ts=saved_at_val))
    if not entries:
        return None
    created_at_val = _to_float(payload.get("created_at_ts"), time.time())
    source_id = payload.get("source_id")
    if source_id is not None and not isinstance(source_id, str):
        source_id = None
    return ClipboardManifest(entries=entries, created_at_ts=created_at_val, source_id=source_id)


def next_session_token() -> str:
    return f"pid-{os.getpid()}"


def _to_float(value: Any, default: float) -> float:
    try:
        if value is None:
            raise TypeError("value is None")
        return float(value)
    except (TypeError, ValueError):
        return default
