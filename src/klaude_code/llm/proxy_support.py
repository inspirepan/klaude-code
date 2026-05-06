from __future__ import annotations

import os
from collections.abc import Iterator, Mapping

SOCKS_PROXY_ENV_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)

_SOCKS_PROXY_SCHEMES = ("socks://", "socks4://", "socks4a://", "socks5://", "socks5h://")


def configured_socks_proxy_var(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    for name in SOCKS_PROXY_ENV_VARS:
        value = env.get(name)
        if value and value.strip().lower().startswith(_SOCKS_PROXY_SCHEMES):
            return name
    return None


def is_missing_socks_proxy_support_error(exc: BaseException) -> bool:
    for current in _iter_exception_chain(exc):
        if not isinstance(current, ImportError):
            continue
        message = str(current).lower()
        if "socks" in message and ("socksio" in message or "python-socks" in message):
            return True
    return False


def _iter_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__
