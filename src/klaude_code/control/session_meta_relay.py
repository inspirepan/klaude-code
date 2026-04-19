from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import queue
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from klaude_code.const import get_system_temp
from klaude_code.log import DebugType, log_debug

RELAY_STREAM_LIMIT = 1024 * 1024

def session_meta_relay_socket_path(*, home_dir: Path | None = None) -> Path:
    resolved_home = (home_dir or Path.home()).resolve()
    suffix = hashlib.sha1(str(resolved_home).encode("utf-8")).hexdigest()[:12]
    return Path(get_system_temp()) / f"klaude-web-session-meta-{suffix}.sock"

@dataclass(frozen=True)
class SessionMetaRelayMessage:
    kind: Literal["upsert", "delete"]
    session_id: str
    meta: dict[str, Any] | None = None

def parse_session_meta_relay_message(raw: bytes) -> SessionMetaRelayMessage:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid session meta relay payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("session meta relay payload must be an object")
    payload_dict = cast(dict[str, Any], payload)
    kind = payload_dict.get("kind")
    session_id = payload_dict.get("session_id")
    meta = payload_dict.get("meta")
    if kind not in {"upsert", "delete"}:
        raise ValueError("invalid session meta relay kind")
    if not isinstance(session_id, str) or session_id == "":
        raise ValueError("invalid session meta relay session_id")
    if meta is not None and not isinstance(meta, dict):
        raise ValueError("invalid session meta relay meta")
    return SessionMetaRelayMessage(
        kind=cast(Literal["upsert", "delete"], kind),
        session_id=session_id,
        meta=cast(dict[str, Any] | None, meta),
    )

class SessionMetaRelayPublisher:
    def __init__(self, *, socket_path: Path, queue_maxsize: int = 2048) -> None:
        self._socket_path = socket_path
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=queue_maxsize)
        self._thread: threading.Thread | None = None
        self._closed = False
        self._lock = threading.Lock()

    def publish_upsert(self, session_id: str, meta: dict[str, Any]) -> None:
        self._publish({"kind": "upsert", "session_id": session_id, "meta": meta})

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is None:
            return
        self._queue.put(None)
        thread.join(timeout=1.0)

    def _publish(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="session-meta-relay", daemon=True)
                self._thread.start()
        try:
            self._queue.put_nowait(json.dumps(payload, ensure_ascii=False))
        except queue.Full:
            return

    def _run(self) -> None:
        conn: socket.socket | None = None
        try:
            while True:
                payload = self._queue.get()
                try:
                    if payload is None:
                        return
                    conn = self._ensure_conn(conn)
                    if conn is None:
                        continue
                    if self._send(conn, payload):
                        continue
                    conn = self._ensure_conn(None)
                    if conn is None:
                        continue
                    _ = self._send(conn, payload)
                finally:
                    self._queue.task_done()
        finally:
            if conn is not None:
                with contextlib.suppress(OSError):
                    conn.close()

    def _ensure_conn(self, conn: socket.socket | None) -> socket.socket | None:
        if conn is not None:
            return conn
        if not self._socket_path.exists():
            return None
        next_conn: socket.socket | None = None
        try:
            next_conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            next_conn.connect(str(self._socket_path))
        except OSError:
            if next_conn is not None:
                with contextlib.suppress(OSError):
                    next_conn.close()
            return None
        return next_conn

    def _send(self, conn: socket.socket, payload: str) -> bool:
        try:
            conn.sendall(payload.encode("utf-8") + b"\n")
            return True
        except OSError:
            with contextlib.suppress(OSError):
                conn.close()
            return False

class SessionMetaRelayServer:
    def __init__(
        self,
        *,
        socket_path: Path,
        on_message: Callable[[SessionMetaRelayMessage], None],
    ) -> None:
        self._socket_path = socket_path
        self._on_message = on_message
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            if await self._is_socket_live():
                raise RuntimeError(f"session meta relay socket already in use: {self._socket_path}")
            self._socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self._socket_path),
            limit=RELAY_STREAM_LIMIT,
        )

    async def aclose(self) -> None:
        if self._server is not None:
            log_debug(
                f"[web] session meta relay close start connections={len(self._connections)}",
                debug_type=DebugType.EXECUTION,
            )
            self._server.close()
            for writer in list(self._connections):
                writer.close()
            for writer in list(self._connections):
                with contextlib.suppress(OSError):
                    await writer.wait_closed()
            await self._server.wait_closed()
            self._server = None
            log_debug("[web] session meta relay close done", debug_type=DebugType.EXECUTION)
        with contextlib.suppress(FileNotFoundError):
            self._socket_path.unlink()

    async def _is_socket_live(self) -> bool:
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
        except OSError:
            return False
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        del reader
        return True

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._connections.add(writer)
        try:
            while True:
                try:
                    raw = await reader.readline()
                except ValueError:
                    return
                if not raw:
                    return
                try:
                    message = parse_session_meta_relay_message(raw)
                except ValueError:
                    continue
                self._on_message(message)
        finally:
            self._connections.discard(writer)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
