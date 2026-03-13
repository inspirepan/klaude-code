from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from .conftest import AppEnv


def test_file_access_allowed_work_dir(app_env: AppEnv) -> None:
    file_path = app_env.work_dir / "hello.txt"
    file_path.write_text("hello", encoding="utf-8")

    response = app_env.client.get("/api/files", params={"path": str(file_path)})
    assert response.status_code == 200
    assert response.text == "hello"


def test_file_access_allowed_tmp(app_env: AppEnv) -> None:
    tmp_file_name = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="klaude-web-", suffix=".txt", delete=False, dir="/tmp") as tmp_file:
            tmp_file_name = tmp_file.name
            tmp_file.write(b"tmp-ok")
        response = app_env.client.get("/api/files", params={"path": tmp_file_name})
        assert response.status_code == 200
        assert response.text == "tmp-ok"
    finally:
        with contextlib.suppress(OSError):
            if tmp_file_name:
                os.unlink(tmp_file_name)


def test_file_access_denied_path_traversal(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/files", params={"path": "/etc/passwd"})
    assert response.status_code == 403


def test_file_access_denied_dotdot(app_env: AppEnv) -> None:
    bad_path = app_env.work_dir / ".." / ".." / "etc" / "passwd"
    response = app_env.client.get("/api/files", params={"path": str(bad_path)})
    assert response.status_code == 403


def test_file_not_found(app_env: AppEnv) -> None:
    missing = app_env.work_dir / "missing.txt"
    response = app_env.client.get("/api/files", params={"path": str(missing)})
    assert response.status_code == 404


def test_image_upload_stores_tmp_file(app_env: AppEnv) -> None:
    data_url = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
    )
    uploaded_path = ""
    try:
        response = app_env.client.post(
            "/api/files/images",
            json={"data_url": data_url, "file_name": "pixel.png"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] == "image_file"
        assert payload["mime_type"] == "image/png"
        uploaded_path = payload["file_path"]
        assert uploaded_path.startswith("/tmp/klaude-web-images/")

        file_response = app_env.client.get("/api/files", params={"path": uploaded_path})
        assert file_response.status_code == 200
        assert file_response.headers["content-type"] == "image/png"
    finally:
        with contextlib.suppress(OSError):
            if uploaded_path:
                os.unlink(uploaded_path)


def test_file_search_lists_current_directory(app_env: AppEnv) -> None:
    (app_env.work_dir / "src").mkdir()
    (app_env.work_dir / "notes.md").write_text("hello", encoding="utf-8")
    (app_env.work_dir / ".git").mkdir()

    response = app_env.client.get("/api/files/search")

    assert response.status_code == 200
    assert response.json()["items"] == ["src/", "notes.md"]


def test_file_search_uses_session_work_dir(app_env: AppEnv, tmp_path: Path) -> None:
    other_work_dir = tmp_path / "other-work"
    (other_work_dir / "nested").mkdir(parents=True)
    (other_work_dir / "nested" / "example.py").write_text("print('ok')\n", encoding="utf-8")
    session_id = app_env.create_session(other_work_dir)

    response = app_env.client.get(
        "/api/files/search",
        params={"session_id": session_id, "query": "exam"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == ["nested/example.py"]


def test_file_search_uses_requested_work_dir(app_env: AppEnv, tmp_path: Path) -> None:
    draft_work_dir = tmp_path / "draft-work"
    (draft_work_dir / "docs").mkdir(parents=True)
    (draft_work_dir / "docs" / "notes with spaces.md").write_text("hello", encoding="utf-8")

    response = app_env.client.get(
        "/api/files/search",
        params={"work_dir": str(draft_work_dir), "query": "notes"},
    )

    assert response.status_code == 200
    assert response.json()["items"] == ["docs/notes with spaces.md"]
