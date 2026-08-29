"""Shared HTTP timeout and transport helpers for LLM clients."""

import os
import socket
import ssl

import certifi
import httpx

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.log import log_debug

try:
    from httpx._utils import get_environment_proxies
except ImportError:
    # Installed (non-lockfile) environments may resolve a newer httpx whose
    # internals moved; degrade to no keepalive rather than fail at import.
    get_environment_proxies = None  # ty: ignore[invalid-assignment]

# TCP keepalive cadence: start probing after 60s idle, then every 10s, giving
# up after 3 unanswered probes (~90s total). A connection idle through an OS
# suspend looks healthy locally but is dead at the peer; without keepalive the
# first request after wake hangs until the read timeout (285s). Kernel
# keepalive timers fire promptly after wake, so the dead peer is detected in
# about a minute and the request fails fast into the retry loop instead.
_TCP_KEEPALIVE_IDLE_SECONDS = 60
_TCP_KEEPALIVE_INTERVAL_SECONDS = 10
_TCP_KEEPALIVE_PROBE_COUNT = 3


def create_http_timeout() -> httpx.Timeout:
    """Standard LLM client timeout: total budget with separate connect/read limits."""
    return httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ)


def create_image_fetch_timeout() -> httpx.Timeout:
    """Timeout for synchronous image fetches (read budget without a separate total)."""
    return httpx.Timeout(LLM_HTTP_TIMEOUT_READ, connect=LLM_HTTP_TIMEOUT_CONNECT)


def create_http_transport(*, proxy: str | None = None) -> httpx.AsyncHTTPTransport:
    """Async transport with TCP keepalive so dead connections fail fast.

    Note: httpx does not forward socket_options on its SOCKS-proxy branch, so
    socks:// proxies get proxied connections without keepalive.
    """
    return httpx.AsyncHTTPTransport(
        proxy=proxy,
        socket_options=_tcp_keepalive_socket_options(),
        verify=_create_ssl_context(),
    )


def create_async_http_client() -> httpx.AsyncClient:
    """Async httpx client with the standard LLM timeout and TCP keepalive.

    Handing httpx an explicit transport disables its env-proxy handling, so
    the HTTP(S)_PROXY/ALL_PROXY mounts (with NO_PROXY exclusions) are rebuilt
    here on keepalive-enabled transports; without this, users behind a proxy
    would be bypassed entirely. SDK call sites still pass ``timeout=`` to the
    SDK itself: the SDKs apply it per request, and both derive from the same
    LLM_HTTP_TIMEOUT_* constants.
    """
    if get_environment_proxies is None:
        # Env-proxy rebuild is impossible without httpx internals; fall back
        # to httpx defaults (env proxies keep working, keepalive is lost).
        log_debug("httpx._utils.get_environment_proxies unavailable; TCP keepalive disabled")
        return httpx.AsyncClient(timeout=create_http_timeout(), follow_redirects=True)
    mounts: dict[str, httpx.AsyncHTTPTransport | None] = {
        pattern: None if proxy_url is None else create_http_transport(proxy=proxy_url)
        for pattern, proxy_url in get_environment_proxies().items()
    }
    # follow_redirects mirrors the openai/anthropic SDK default clients.
    return httpx.AsyncClient(
        timeout=create_http_timeout(),
        transport=create_http_transport(),
        mounts=mounts,
        follow_redirects=True,
    )


def _create_ssl_context() -> ssl.SSLContext:
    # Mirror google-genai's semantics: certifi bundle *plus* the env overrides.
    # httpx's default picks SSL_CERT_FILE, else SSL_CERT_DIR, else certifi —
    # never combining — which would drop the certifi bundle on the Google
    # path, whose SDK used to combine them.
    return ssl.create_default_context(
        cafile=os.environ.get("SSL_CERT_FILE", certifi.where()),
        capath=os.environ.get("SSL_CERT_DIR") or None,
    )


def _tcp_keepalive_socket_options() -> list[tuple[int, int, int]]:
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    # macOS spells the idle-time option TCP_KEEPALIVE; Linux/Windows use TCP_KEEPIDLE.
    keepidle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    if keepidle is not None:
        options.append((socket.IPPROTO_TCP, keepidle, _TCP_KEEPALIVE_IDLE_SECONDS))
    if hasattr(socket, "TCP_KEEPINTVL"):
        options.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _TCP_KEEPALIVE_INTERVAL_SECONDS))
    if hasattr(socket, "TCP_KEEPCNT"):
        options.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _TCP_KEEPALIVE_PROBE_COUNT))
    return options
