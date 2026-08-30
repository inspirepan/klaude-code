"""Static serving for the web viewer bundle (`/` and `/assets/*`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from klaude_code.server.routes import web as web_routes

from .conftest import AppEnv


@pytest.fixture
def bundle_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the static routes at a fake `pnpm build` output."""

    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>klaude</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("export const ok = 1;\n", encoding="utf-8")
    monkeypatch.setattr(web_routes, "_PACKAGE_WEB_DIR", dist)
    return dist


def test_index_serves_built_html(app_env: AppEnv, bundle_dir: Path) -> None:
    del bundle_dir
    response = app_env.client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "id=root" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_asset_is_served_with_immutable_cache(app_env: AppEnv, bundle_dir: Path) -> None:
    del bundle_dir
    response = app_env.client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert "export const ok" in response.text
    assert "immutable" in response.headers["cache-control"]


def test_unknown_asset_is_404(app_env: AppEnv, bundle_dir: Path) -> None:
    del bundle_dir
    assert app_env.client.get("/assets/nope.js").status_code == 404


def test_asset_path_cannot_escape_the_bundle(app_env: AppEnv, bundle_dir: Path) -> None:
    secret = bundle_dir.parent / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    response = app_env.client.get("/assets/..%2Fsecret.txt")
    assert response.status_code == 404
    assert "private" not in response.text


def test_missing_bundle_returns_503_with_build_hint(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_routes, "_PACKAGE_WEB_DIR", tmp_path / "not-built")

    response = app_env.client.get("/")

    assert response.status_code == 503
    assert web_routes.BUILD_HINT in response.text


def test_api_routes_take_precedence_over_static(app_env: AppEnv, bundle_dir: Path) -> None:
    del bundle_dir
    response = app_env.client.get("/api/server/status")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_status_reports_no_web_port_without_tcp_listener(app_env: AppEnv) -> None:
    """The app_env fixture builds the app without a web port (UDS-only degradation)."""

    payload = app_env.client.get("/api/server/status").json()
    assert payload["web_port"] is None
    assert payload["web_url"] is None
