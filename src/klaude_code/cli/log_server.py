"""Minimal HTTP server for the debug log viewer."""

import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from klaude_code.const import DEFAULT_DEBUG_LOG_DIR

_VIEWER_HTML = Path(__file__).parent / "log_viewer.html"


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
        if not str(log_path).startswith(str(log_dir)):
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

    def _error(self, code: int, msg: str) -> None:
        body = msg.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_log_viewer(log_path: Path) -> str:
    """Start the log viewer server in a daemon thread and open the browser.

    Returns the URL of the viewer.
    """
    port = _find_free_port()
    server = HTTPServer(("127.0.0.1", port), _LogViewerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/?log={log_path}"
    webbrowser.open(url)
    return url
