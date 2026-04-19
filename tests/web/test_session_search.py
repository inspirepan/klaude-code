from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .conftest import AppEnv


def _meta_path_for_session(app_env: AppEnv, session_id: str) -> Path:
    candidates = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(candidates) == 1
    return candidates[0]

def _update_meta(app_env: AppEnv, session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    meta_path = _meta_path_for_session(app_env, session_id)
    raw_meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(raw_meta_obj, dict)
    raw_meta = cast(dict[str, Any], raw_meta_obj)
    raw_meta.update(updates)
    meta_path.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_meta

def test_search_sessions_empty_query_returns_empty(app_env: AppEnv) -> None:
    app_env.create_session()
    response = app_env.client.get("/api/sessions/search", params={"q": ""})
    assert response.status_code == 200
    assert response.json()["results"] == []

def test_search_sessions_no_match(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _update_meta(app_env, session_id, {"title": "Hello World"})

    response = app_env.client.get("/api/sessions/search", params={"q": "nonexistent_xyz"})
    assert response.status_code == 200
    assert response.json()["results"] == []

def test_search_sessions_by_title(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    s2 = app_env.create_session()
    _update_meta(app_env, s1, {"title": "Fix login bug"})
    _update_meta(app_env, s2, {"title": "Refactor database"})

    response = app_env.client.get("/api/sessions/search", params={"q": "login"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == s1
    assert results[0]["title"] == "Fix login bug"

def test_search_sessions_by_user_message(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    _update_meta(app_env, s1, {"user_messages": ["Help me write a unit test", "Also add type hints"]})

    response = app_env.client.get("/api/sessions/search", params={"q": "unit test"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == s1

def test_search_sessions_by_work_dir(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    _update_meta(app_env, s1, {"work_dir": "/home/user/my-cool-project"})

    response = app_env.client.get("/api/sessions/search", params={"q": "my-cool-project"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == s1

def test_search_sessions_case_insensitive(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    _update_meta(app_env, s1, {"title": "Fix Login Bug"})

    response = app_env.client.get("/api/sessions/search", params={"q": "fix login"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["id"] == s1

def test_search_sessions_includes_archived(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    s2 = app_env.create_session()
    _update_meta(app_env, s1, {"title": "Active feature", "archived": False})
    _update_meta(app_env, s2, {"title": "Archived feature", "archived": True})

    response = app_env.client.get("/api/sessions/search", params={"q": "feature"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    ids = {r["id"] for r in results}
    assert s1 in ids
    assert s2 in ids
    archived_result = next(r for r in results if r["id"] == s2)
    assert archived_result["archived"] is True

def test_search_sessions_returns_expected_fields(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    _update_meta(
        app_env,
        s1,
        {
            "title": "My Session",
            "user_messages": ["hello world"],
            "archived": False,
        },
    )

    response = app_env.client.get("/api/sessions/search", params={"q": "My Session"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    result = results[0]
    assert result["id"] == s1
    assert result["title"] == "My Session"
    assert result["user_messages"] == ["hello world"]
    assert result["archived"] is False
    assert "work_dir" in result
    assert "created_at" in result
    assert "updated_at" in result

def test_search_sessions_sorted_by_updated_at(app_env: AppEnv) -> None:
    s1 = app_env.create_session()
    s2 = app_env.create_session()
    s3 = app_env.create_session()
    _update_meta(app_env, s1, {"title": "Task Alpha", "updated_at": 1000.0})
    _update_meta(app_env, s2, {"title": "Task Beta", "updated_at": 3000.0})
    _update_meta(app_env, s3, {"title": "Task Gamma", "updated_at": 2000.0})

    response = app_env.client.get("/api/sessions/search", params={"q": "Task"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    assert results[0]["id"] == s2
    assert results[1]["id"] == s3
    assert results[2]["id"] == s1
