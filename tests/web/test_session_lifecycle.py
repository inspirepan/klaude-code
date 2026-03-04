from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .conftest import AppEnv


def test_create_list_delete_list(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json()["groups"] == []

    create_response = app_env.client.post("/api/sessions", json={"work_dir": str(app_env.work_dir)})
    assert create_response.status_code == 200
    session_id = str(create_response.json()["session_id"])

    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["work_dir"] == str(app_env.work_dir)
    sessions = groups[0]["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id

    delete_response = app_env.client.delete(f"/api/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True

    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json()["groups"] == []


def test_create_session_invalid_work_dir(app_env: AppEnv, tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist"
    response = app_env.client.post("/api/sessions", json={"work_dir": str(missing_path)})
    assert response.status_code == 400


def test_sub_agent_sessions_filtered_from_list(app_env: AppEnv) -> None:
    main_session_id = app_env.create_session()

    sessions_dirs = list((app_env.home_dir / ".klaude" / "projects").glob("*/sessions"))
    assert sessions_dirs
    sessions_dir = sessions_dirs[0]

    sub_session_id = "subagent-session-id"
    sub_dir = sessions_dir / sub_session_id
    sub_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "id": sub_session_id,
        "work_dir": str(app_env.work_dir),
        "sub_agent_state": {
            "sub_agent_type": "general-purpose",
            "sub_agent_desc": "sub",
            "sub_agent_prompt": "prompt",
        },
        "created_at": time.time(),
        "updated_at": time.time(),
        "user_messages": [],
        "messages_count": 0,
        "model_name": "fake-model",
    }
    (sub_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    response = app_env.client.get("/api/sessions")
    assert response.status_code == 200
    all_ids = [session["id"] for group in response.json()["groups"] for session in group["sessions"]]
    assert main_session_id in all_ids
    assert sub_session_id not in all_ids
