import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from klaude_code.protocol import message
from klaude_code.protocol.models.session_status import SessionActiveTurn
from klaude_code.server.read_only import create_read_only_app
from klaude_code.session import Session


def test_history_server_refreshes_disk_without_runtime(isolated_home: Path, tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    session.ensure_meta_exists()
    app = create_read_only_app(home_dir=isolated_home)
    assert not hasattr(app.state, "server_state")
    with TestClient(app) as client:
        first = client.get(f"/api/web/sessions/{session.id}/meta")
        assert first.status_code == 200
        assert "loaded" not in first.json()
        assert first.json()["line_count"] == 0

        async def append() -> None:
            session.append_history([message.UserMessage(parts=[message.TextPart(text="landed on disk")])])
            await session.wait_for_flush()

        asyncio.run(append())
        later = client.get(f"/api/web/sessions/{session.id}/meta").json()
        assert later["line_count"] > first.json()["line_count"]
        history = client.get(f"/api/web/sessions/{session.id}/history").json()
        assert "landed on disk" in str(history)
        rows = client.get("/api/web/sessions").json()["sessions"]
        assert rows[0]["id"] == session.id
        assert client.post("/api/headless/run", json={"prompt": "never execute"}).status_code == 404
        assert (
            client.post(f"/api/headless/sessions/{session.id}/send", json={"text": "never execute"}).status_code == 404
        )
        assert not hasattr(app.state, "server_state")
        assert client.get("/api/headless/sessions").status_code == 404


def test_web_reports_persisted_execution_without_declaring_it_offline(isolated_home: Path, tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    session.ensure_meta_exists()
    session.runtime.active_turn = SessionActiveTurn(id="persisted-turn", started=True)
    session.persist_runtime()
    with TestClient(create_read_only_app(home_dir=isolated_home)) as client:
        meta = client.get(f"/api/web/sessions/{session.id}/meta").json()
        assert "loaded" not in meta
        assert meta["status"]["execution"] == "running"
        assert meta["status"]["last_turn"] is None
