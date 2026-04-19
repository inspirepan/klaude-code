from __future__ import annotations

import json
import time
from typing import Any, cast

from .conftest import AppEnv


def test_list_sessions_includes_todos_and_file_change_summary(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    meta_path = next((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))

    raw_obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_obj, dict)
    raw = cast(dict[str, Any], raw_obj)
    raw["updated_at"] = time.time()
    raw["todos"] = [
        {"content": "Plan changes", "status": "completed"},
        {"content": "Build UI", "status": "in_progress"},
    ]
    raw["file_change_summary"] = {
        "created_files": ["/tmp/created.tsx"],
        "edited_files": ["/tmp/edited.tsx"],
        "diff_lines_added": 12,
        "diff_lines_removed": 4,
        "file_diffs": {
            "/tmp/created.tsx": {"added": 8, "removed": 0},
            "/tmp/edited.tsx": {"added": 4, "removed": 4},
        },
    }
    meta_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    groups = response.json()["groups"]
    listed_session = next(session for group in groups for session in group["sessions"] if session["id"] == session_id)

    assert listed_session["todos"] == [
        {"content": "Plan changes", "status": "completed"},
        {"content": "Build UI", "status": "in_progress"},
    ]
    assert listed_session["file_change_summary"] == {
        "created_files": ["/tmp/created.tsx"],
        "edited_files": ["/tmp/edited.tsx"],
        "diff_lines_added": 12,
        "diff_lines_removed": 4,
        "file_diffs": {
            "/tmp/created.tsx": {"added": 8, "removed": 0},
            "/tmp/edited.tsx": {"added": 4, "removed": 4},
        },
    }

def test_list_sessions_defaults_missing_summary_fields(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    meta_path = next((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))

    raw_obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_obj, dict)
    raw = cast(dict[str, Any], raw_obj)
    raw["updated_at"] = time.time()
    raw.pop("todos", None)
    raw.pop("file_change_summary", None)
    meta_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    groups = response.json()["groups"]
    listed_session = next(session for group in groups for session in group["sessions"] if session["id"] == session_id)

    assert listed_session["todos"] == []
    assert listed_session["file_change_summary"] == {
        "created_files": [],
        "edited_files": [],
        "diff_lines_added": 0,
        "diff_lines_removed": 0,
        "file_diffs": {},
    }
