from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .conftest import AppEnv


def _meta_path_for_session(app_env: AppEnv, session_id: str) -> Path:
    candidates = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(candidates) == 1
    return candidates[0]


def _find_listed_session(groups: list[dict[str, Any]], session_id: str) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    for group in groups:
        raw_sessions_obj = group.get("sessions")
        if not isinstance(raw_sessions_obj, list):
            continue
        raw_sessions = cast(list[Any], raw_sessions_obj)
        for session in raw_sessions:
            if isinstance(session, dict):
                sessions.append(cast(dict[str, Any], session))
    for session in sessions:
        if session.get("id") == session_id:
            return session
    raise AssertionError(f"Session not found in listing: {session_id}")


def test_archive_session_marks_metadata_and_listed_flag(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    before_archive = app_env.client.get("/api/sessions")
    assert before_archive.status_code == 200
    listed_before = _find_listed_session(before_archive.json()["groups"], session_id)
    assert listed_before["archived"] is False

    archive_response = app_env.client.post(f"/api/sessions/{session_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["ok"] is True

    after_archive = app_env.client.get("/api/sessions")
    assert after_archive.status_code == 200
    listed_after = _find_listed_session(after_archive.json()["groups"], session_id)
    assert listed_after["archived"] is True

    meta_path = _meta_path_for_session(app_env, session_id)
    raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_meta, dict)
    assert raw_meta["archived"] is True


def test_archive_session_not_found(app_env: AppEnv) -> None:
    response = app_env.client.post("/api/sessions/missing/archive")
    assert response.status_code == 404


def test_unarchive_session_marks_metadata_and_listed_flag(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    archive_response = app_env.client.post(f"/api/sessions/{session_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["ok"] is True

    unarchive_response = app_env.client.post(f"/api/sessions/{session_id}/unarchive")
    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["ok"] is True

    listed = app_env.client.get("/api/sessions")
    assert listed.status_code == 200
    listed_session = _find_listed_session(listed.json()["groups"], session_id)
    assert listed_session["archived"] is False

    meta_path = _meta_path_for_session(app_env, session_id)
    raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_meta, dict)
    assert raw_meta["archived"] is False


def test_unarchive_session_not_found(app_env: AppEnv) -> None:
    response = app_env.client.post("/api/sessions/missing/unarchive")
    assert response.status_code == 404
