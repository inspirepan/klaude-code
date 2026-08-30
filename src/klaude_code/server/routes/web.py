"""Static serving for the built web viewer bundle.

The bundle is a Vite build (`cd web && pnpm build`) that lands inside the
package at ``klaude_code/server/web/``: ``index.html`` plus content-hashed
files under ``assets/``. Routing is client-side, so only ``/`` needs the HTML.

Paths are resolved from this module's location, never from the process CWD
(the server chdir's to $HOME at startup and TID251 bans CWD APIs here).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

router = APIRouter(tags=["web"])

# Module-level so tests can point it at a fixture directory.
_PACKAGE_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

BUILD_HINT = "cd web && pnpm install && pnpm build"


def web_dist_dir() -> Path:
    return _PACKAGE_WEB_DIR


def web_index_file() -> Path:
    return web_dist_dir() / "index.html"


def is_web_bundle_available() -> bool:
    return web_index_file().is_file()


def missing_bundle_html() -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>klaude web viewer is not built</title></head>
<body style="font-family: system-ui, sans-serif; margin: 3rem auto; max-width: 40rem; line-height: 1.6">
<h1>Web bundle not built</h1>
<p>The klaude server is running, but the viewer's static files are missing from
<code>{web_dist_dir()}</code>.</p>
<p>Build them from a source checkout:</p>
<pre style="background:#f4f4f5;padding:0.75rem;border-radius:6px"><code>{BUILD_HINT}</code></pre>
<p>The API is unaffected: <code>/api/server/status</code> and the rest of
<code>/api/...</code> answer normally.</p>
</body>
</html>
"""


@router.get("/", include_in_schema=False)
async def get_web_index() -> Response:
    index = web_index_file()
    if not index.is_file():
        return HTMLResponse(missing_bundle_html(), status_code=503)
    # The HTML names hashed asset files, so it must never be cached.
    return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/assets/{asset_path:path}", include_in_schema=False)
async def get_web_asset(asset_path: str) -> Response:
    assets_dir = (web_dist_dir() / "assets").resolve()
    target = (assets_dir / asset_path).resolve()
    if not target.is_relative_to(assets_dir) or not target.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    # Vite hashes every asset filename, so a hit is immutable.
    return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
