"""On-demand HTTP server for persisted history only."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from klaude_code.app.process_queries import persisted_status
from klaude_code.app.session_index import SessionIndex
from klaude_code.server.host_guard import HostHeaderGuardMiddleware
from klaude_code.server.routes.web import router as web_router
from klaude_code.server.routes.web_api import router as web_api_router
from klaude_code.server.web_state import ReadOnlyWebState
from klaude_code.session import Session


def create_read_only_app(*, home_dir: Path | None = None, web_port: int = 8765) -> FastAPI:
    home = home_dir or Path.home()
    state = ReadOnlyWebState(home_dir=home, index=SessionIndex(home=home))
    app = FastAPI()
    app.state.web_state = state
    app.add_middleware(HostHeaderGuardMiddleware, web_port=web_port)
    app.include_router(web_api_router)

    @app.get("/api/web/sessions")
    def list_history(
        limit: int = 200, include_children: bool = False, include_archived: bool = False
    ) -> dict[str, Any]:
        state.index.reload()
        rows = []
        for summary in state.index.list_all():
            if not include_children and summary.parent_session_id is not None:
                continue
            if not include_archived and summary.archived:
                continue
            session = Session.load_meta(summary.id, work_dir=Path(summary.work_dir))
            status = persisted_status(session)
            row = asdict(summary)
            row.update(
                state=status.category,
                status=status.model_dump(mode="json"),
                model=summary.model_config_name or summary.model_name,
            )
            rows.append(row)
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return {"sessions": rows[:limit] if limit > 0 else rows}

    app.include_router(web_router)
    return app
