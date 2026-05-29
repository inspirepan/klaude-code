"""Shared HTTP timeout helpers for LLM clients."""

import httpx

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL


def create_http_timeout() -> httpx.Timeout:
    """Standard LLM client timeout: total budget with separate connect/read limits."""
    return httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ)


def create_image_fetch_timeout() -> httpx.Timeout:
    """Timeout for synchronous image fetches (read budget without a separate total)."""
    return httpx.Timeout(LLM_HTTP_TIMEOUT_READ, connect=LLM_HTTP_TIMEOUT_CONNECT)
