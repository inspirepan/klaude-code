from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from klaude_code.const import get_system_temp
from klaude_code.llm.image import normalize_image_data_url, parse_data_url
from klaude_code.protocol.message import ImageFilePart
from klaude_code.web.file_access import validate_file_access
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/files", tags=["files"])
WEB_STATE_DEP: Final = Depends(get_web_state)

_IMAGE_MIME_SUFFIXES: Final = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class UploadImageRequest(BaseModel):
    data_url: str
    file_name: str | None = None


def _resolve_image_suffix(*, mime_type: str, file_name: str | None) -> str | None:
    suffix = Path(file_name).suffix.lower() if file_name else ""
    guessed_mime, _ = mimetypes.guess_type(f"x{suffix}") if suffix else (None, None)
    if suffix and guessed_mime == mime_type and suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return suffix
    return _IMAGE_MIME_SUFFIXES.get(mime_type)


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


@router.post("/images")
async def upload_image(
    payload: UploadImageRequest,
    state: WebAppState = WEB_STATE_DEP,
) -> ImageFilePart:
    del state
    try:
        normalized = normalize_image_data_url(payload.data_url)
        mime_type, _, decoded = parse_data_url(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    suffix = _resolve_image_suffix(mime_type=mime_type, file_name=payload.file_name)
    if suffix is None:
        raise HTTPException(status_code=400, detail=f"unsupported image type: {mime_type}")

    images_dir = Path(get_system_temp()) / "klaude-web-images"
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
        file_path = images_dir / f"klaude-web-image-{uuid4().hex}{suffix}"
        file_path.write_bytes(decoded)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to store uploaded image: {exc}") from exc

    return ImageFilePart(file_path=str(file_path), mime_type=mime_type, byte_size=len(decoded))
