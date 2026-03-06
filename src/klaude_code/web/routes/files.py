from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from klaude_code.web.file_access import validate_file_access
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/files", tags=["files"])
WEB_STATE_DEP: Final = Depends(get_web_state)


@router.get("")
async def get_file(
    path: str = Query(..., description="Absolute local file path"),
    state: WebAppState = WEB_STATE_DEP,
) -> FileResponse:
    status_code, resolved = validate_file_access(path, work_dir=state.work_dir, home_dir=state.home_dir)
    if status_code != 200 or resolved is None:
        if status_code == 400:
            raise HTTPException(status_code=400, detail="path must be absolute")
        if status_code == 403:
            raise HTTPException(status_code=403, detail="file access denied")
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=str(resolved))
