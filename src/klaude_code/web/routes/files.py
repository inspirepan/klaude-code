from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
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
from klaude_code.web.session_index import resolve_session_work_dir
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/files", tags=["files"])
WEB_STATE_DEP: Final = Depends(get_web_state)
_SEARCH_EXCLUDED_DIRS: Final = {".git", ".venv", "node_modules"}

_IMAGE_MIME_SUFFIXES: Final = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class UploadImageRequest(BaseModel):
    data_url: str
    file_name: str | None = None


class SearchFilesResponse(BaseModel):
    items: list[str]


def _run_search_command(cmd: list[str], *, cwd: Path) -> list[str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.75,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _normalize_search_path(path: str) -> str:
    return path.removeprefix("./").removeprefix(".\\")


def _rank_paths(work_dir: Path, paths: list[str], *, keyword: str) -> list[str]:
    ranked: list[tuple[str, tuple[int, int, int, int, int, int, int, int]]] = []
    for raw_path in paths:
        rel_path = _normalize_search_path(raw_path)
        path_lower = rel_path.lower()
        if keyword not in path_lower:
            continue

        base_name = os.path.basename(rel_path.rstrip("/")).lower()
        base_pos = base_name.find(keyword)
        path_pos = path_lower.find(keyword)
        depth = rel_path.rstrip("/").count("/")
        is_hidden = any(segment.startswith(".") for segment in rel_path.split("/") if segment)
        has_test = "test" in path_lower
        base_stem = base_name.rsplit(".", 1)[0] if "." in base_name and not base_name.startswith(".") else base_name
        base_match_quality = abs(len(base_stem) - len(keyword)) if base_pos != -1 else 10_000

        ranked.append(
            (
                rel_path,
                (
                    1 if is_hidden else 0,
                    1 if has_test else 0,
                    0 if base_pos != -1 else 1,
                    base_match_quality,
                    depth,
                    base_pos if base_pos != -1 else 10_000,
                    path_pos,
                    len(rel_path),
                ),
            )
        )

    ranked.sort(key=lambda item: item[1])

    unique_paths: list[str] = []
    seen: set[str] = set()
    for rel_path, _score in ranked:
        normalized = rel_path.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            if (work_dir / normalized).is_dir():
                unique_paths.append(f"{normalized}/")
            else:
                unique_paths.append(normalized)
        except OSError:
            unique_paths.append(normalized)
    return unique_paths


def _search_current_dir(work_dir: Path, *, limit: int) -> list[str]:
    try:
        items = list(work_dir.iterdir())
    except OSError:
        return []

    def sort_key(path: Path) -> tuple[int, int, int, str]:
        name = path.name
        return (
            1 if name.startswith(".") else 0,
            1 if "test" in name.lower() else 0,
            1 if path.is_file() else 0,
            name.lower(),
        )

    results: list[str] = []
    for item in sorted(items, key=sort_key):
        if item.name in _SEARCH_EXCLUDED_DIRS:
            continue
        results.append(f"{item.name}/" if item.is_dir() else item.name)
        if len(results) >= limit:
            break
    return results


def _search_with_fd(work_dir: Path, *, keyword: str, limit: int) -> list[str]:
    if shutil.which("fd") is None:
        return []

    immediate: list[str] = []
    try:
        for item in work_dir.iterdir():
            if item.name in _SEARCH_EXCLUDED_DIRS or keyword not in item.name.lower():
                continue
            immediate.append(f"{item.name}/" if item.is_dir() else item.name)
    except OSError:
        immediate = []

    command = [
        "fd",
        "--color=never",
        "--type",
        "f",
        "--type",
        "d",
        "--hidden",
        "--full-path",
        "-i",
        "-F",
        "--max-results",
        str(limit * 4),
        "--exclude",
        ".git",
        "--exclude",
        ".venv",
        "--exclude",
        "node_modules",
        keyword,
        ".",
    ]
    return immediate + _run_search_command(command, cwd=work_dir)


def _search_with_rg(work_dir: Path, *, keyword: str, limit: int) -> list[str]:
    if shutil.which("rg") is None:
        return []
    command = [
        "rg",
        "--files",
        "--hidden",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/.venv/**",
        "--glob",
        "!**/node_modules/**",
    ]
    matches = [path for path in _run_search_command(command, cwd=work_dir) if keyword in path.lower()]
    return matches[: limit * 4]


def _search_with_python(work_dir: Path, *, keyword: str, limit: int) -> list[str]:
    paths: list[str] = []
    try:
        for root, dirs, files in os.walk(work_dir):
            dirs[:] = [name for name in dirs if name not in _SEARCH_EXCLUDED_DIRS]
            root_path = Path(root)
            for dir_name in dirs:
                rel_dir = (root_path / dir_name).relative_to(work_dir).as_posix()
                rel_path = f"{rel_dir}/"
                if keyword in rel_path.lower():
                    paths.append(rel_path)
                    if len(paths) >= limit * 4:
                        return paths
            for file_name in files:
                rel_path = (root_path / file_name).relative_to(work_dir).as_posix()
                if keyword in rel_path.lower():
                    paths.append(rel_path)
                    if len(paths) >= limit * 4:
                        return paths
    except OSError:
        return []
    return paths


def _search_paths(work_dir: Path, *, query: str, limit: int) -> list[str]:
    keyword = query.strip().lower()
    if not keyword:
        return _search_current_dir(work_dir, limit=limit)

    candidates = _search_with_fd(work_dir, keyword=keyword, limit=limit)
    if not candidates:
        candidates = _search_with_rg(work_dir, keyword=keyword, limit=limit)
    if not candidates:
        candidates = _search_with_python(work_dir, keyword=keyword, limit=limit)
    if not candidates:
        return []
    return _rank_paths(work_dir, candidates, keyword=keyword)[:limit]


def _resolve_image_suffix(*, mime_type: str, file_name: str | None) -> str | None:
    suffix = Path(file_name).suffix.lower() if file_name else ""
    guessed_mime, _ = mimetypes.guess_type(f"x{suffix}") if suffix else (None, None)
    if suffix and guessed_mime == mime_type and suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return suffix
    return _IMAGE_MIME_SUFFIXES.get(mime_type)


@router.get("")
async def get_file(
    path: str = Query(..., description="Absolute local file path or session-relative path"),
    session_id: str | None = Query(None, description="Session to resolve workspace from"),
    state: WebAppState = WEB_STATE_DEP,
) -> FileResponse:
    work_dir = state.work_dir
    if session_id:
        resolved_work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if resolved_work_dir is None:
            raise HTTPException(status_code=404, detail="session not found")
        work_dir = resolved_work_dir.resolve()
        requested = Path(path)
        if not requested.is_absolute():
            path = str(work_dir / requested)

    status_code, resolved = validate_file_access(path, work_dir=work_dir, home_dir=state.home_dir)
    if status_code != 200 or resolved is None:
        if status_code == 400:
            raise HTTPException(status_code=400, detail="path must be absolute unless session_id is provided")
        if status_code == 403:
            raise HTTPException(status_code=403, detail="file access denied")
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path=str(resolved))


@router.get("/search")
async def search_files(
    query: str = Query("", description="Path fragment after @"),
    session_id: str | None = Query(None, description="Session to resolve workspace from"),
    raw_work_dir: str | None = Query(None, alias="work_dir", description="Workspace to search before session creation"),
    limit: int = Query(10, ge=1, le=50),
    state: WebAppState = WEB_STATE_DEP,
) -> SearchFilesResponse:
    work_dir = state.work_dir
    if session_id:
        resolved_work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if resolved_work_dir is None:
            raise HTTPException(status_code=404, detail="session not found")
        work_dir = resolved_work_dir.resolve()
    elif raw_work_dir:
        candidate = Path(raw_work_dir).expanduser().resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise HTTPException(status_code=400, detail="work_dir does not exist")
        work_dir = candidate

    return SearchFilesResponse(items=_search_paths(work_dir, query=query, limit=limit))


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
