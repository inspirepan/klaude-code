from __future__ import annotations

import contextlib
import os
import tempfile

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
