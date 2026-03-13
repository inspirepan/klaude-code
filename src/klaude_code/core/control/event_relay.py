from __future__ import annotations

import asyncio
import contextlib
import hashlib
from pathlib import Path

from klaude_code.const import get_system_temp
from klaude_code.core.control.event_bus import EnvelopeBus
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events

RELAY_STREAM_LIMIT = 1024 * 1024


def event_relay_socket_path(*, home_dir: Path | None = None) -> Path:
    resolved_home = (home_dir or Path.home()).resolve()
    suffix = hashlib.sha1(str(resolved_home).encode("utf-8")).hexdigest()[:12]
    return Path(get_system_temp()) / f"klaude-web-events-{suffix}.sock"


class EventRelayPublisher:
    def __init__(self, *, socket_path: Path, queue_maxsize: int = 2048) -> None:
        self._socket_path = socket_path
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def publish(self, envelope: events.EventEnvelope) -> None:
        if self._closed:
            return
        if self._task is None:
            self._task = asyncio.create_task(self._run())

        payload = envelope.model_dump_json(exclude_none=True, serialize_as_any=True)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            log_debug(
                f"[{envelope.session_id}] relay queue overflow: dropping [{envelope.event_type}]",
                debug_type=DebugType.EVENT_BUS,
            )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._task is None:
            return

        await self._queue.put(None)
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        writer: asyncio.StreamWriter | None = None
        try:
            while True:
                payload = await self._queue.get()
                try:
                    if payload is None:
                        return

                    writer = await self._ensure_writer(writer)
                    if writer is None:
                        continue

                    if await self._write_payload(writer, payload):
                        continue

                    writer = await self._ensure_writer(None)
                    if writer is None:
                        continue
                    _ = await self._write_payload(writer, payload)
                finally:
                    self._queue.task_done()
        finally:
            await self._close_writer(writer)

    async def _ensure_writer(self, writer: asyncio.StreamWriter | None) -> asyncio.StreamWriter | None:
        if writer is not None and not writer.is_closing():
            return writer
        if not self._socket_path.exists():
            return None

        try:
            _, writer = await asyncio.open_unix_connection(str(self._socket_path))
        except OSError:
            return None
        return writer

    async def _write_payload(self, writer: asyncio.StreamWriter, payload: str) -> bool:
        try:
            writer.write(payload.encode("utf-8") + b"\n")
            await writer.drain()
            return True
        except OSError:
            await self._close_writer(writer)
            return False

    async def _close_writer(self, writer: asyncio.StreamWriter | None) -> None:
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


class EventRelayServer:
    def __init__(self, *, socket_path: Path, envelope_bus: EnvelopeBus) -> None:
        self._socket_path = socket_path
        self._envelope_bus = envelope_bus
        self._server: asyncio.AbstractServer | None = None
        self._connections: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self._socket_path.exists():
            if await self._is_socket_live():
                raise RuntimeError(f"event relay socket already in use: {self._socket_path}")
            self._socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self._socket_path),
            limit=RELAY_STREAM_LIMIT,
        )

    async def aclose(self) -> None:
        if self._server is not None:
            log_debug(
                f"[web] event relay close start connections={len(self._connections)}",
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
            log_debug("[web] event relay close done", debug_type=DebugType.EXECUTION)
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

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
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
                    envelope = events.parse_event_envelope_json(raw)
                except ValueError:
                    continue
                await self._envelope_bus.publish_envelope(envelope)
        finally:
            self._connections.discard(writer)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
