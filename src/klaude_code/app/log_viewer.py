"""Minimal HTTP server for the debug log viewer."""

import errno
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from klaude_code.const import DEFAULT_DEBUG_LOG_DIR

_VIEWER_HTML = Path(__file__).parent / "log_viewer.html"
_DEFAULT_LOG_VIEWER_PORT = 8765


class _LogViewerHandler(BaseHTTPRequestHandler):
    """Serve the log viewer HTML and log file contents."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "":
            self._serve_html()
        elif parsed.path == "/api/log":
            qs = parse_qs(parsed.query)
            paths = qs.get("path", [])
            if paths:
                self._serve_log(paths[0])
            else:
                self._error(400, "missing path parameter")
        elif parsed.path == "/api/logs":
            self._serve_logs()
        else:
            self._error(404, "not found")

    def _serve_html(self) -> None:
        content = _VIEWER_HTML.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_log(self, raw_path: str) -> None:
        log_path = Path(raw_path).resolve()
        log_dir = DEFAULT_DEBUG_LOG_DIR.resolve()
        if not _is_path_within(log_path, log_dir):
            self._error(403, "access denied: path outside log directory")
            return
        if not log_path.is_file():
            self._error(404, "log file not found")
            return
        content = log_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_logs(self) -> None:
        logs = _list_log_files(DEFAULT_DEBUG_LOG_DIR.resolve())
        body = json.dumps(logs).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, msg: str) -> None:
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _create_server_with_fallback(start_port: int) -> tuple[HTTPServer, int]:
    for port in range(start_port, 65536):
        try:
            server = HTTPServer(("127.0.0.1", port), _LogViewerHandler)
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                continue
            raise
        return server, port
    raise RuntimeError(f"no available port from {start_port} to 65535")


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _list_log_files(log_dir: Path) -> list[dict[str, object]]:
    if not log_dir.exists():
        return []

    files: list[tuple[float, dict[str, object]]] = []
    seen_paths: set[Path] = set()
    for path in log_dir.rglob("*.log"):
        if not path.is_file():
            continue

        try:
            stat = path.stat()
            resolved = path.resolve()
            relative_path = str(resolved.relative_to(log_dir))
        except (OSError, ValueError):
            continue

        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)

        files.append(
            (
                stat.st_mtime,
                {
                    "path": str(resolved),
                    "relative_path": relative_path,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                },
            )
        )

    files.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in files]


def start_log_viewer(log_path: Path) -> str:
    """Start the log viewer server in a daemon thread and open the browser.

    Returns the URL of the viewer.
    """
    server, port = _create_server_with_fallback(_DEFAULT_LOG_VIEWER_PORT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/?log={log_path}"
    webbrowser.open(url)
    return url
