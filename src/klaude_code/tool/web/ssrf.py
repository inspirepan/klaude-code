"""SSRF (Server-Side Request Forgery) protection for web tools.

Validates that URLs do not resolve to private/internal network addresses
before allowing HTTP requests. This prevents LLM-directed requests from
reaching localhost, cloud metadata endpoints, or internal services.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal"})
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal")
_BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class SSRFBlockedError(Exception):
    """Raised when a URL is blocked by SSRF protection."""


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is private, loopback, link-local, or reserved."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False  # not an IP address, skip IP check (DNS resolution will handle it)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _is_blocked_hostname(hostname: str) -> bool:
    """Check if hostname is in the blocklist."""
    normalized = hostname.lower().rstrip(".")
    if normalized in _BLOCKED_HOSTNAMES:
        return True
    return any(normalized.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)


def _is_benchmark_ip(ip_str: str) -> bool:
    try:
        return ipaddress.ip_address(ip_str) in _BENCHMARK_NETWORK
    except ValueError:
        return False


def check_ssrf(url: str) -> None:
    """Validate that a URL does not target private/internal resources.

    Raises SSRFBlockedError if the URL is blocked.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError(f"No hostname in URL: {url}")

    if _is_blocked_hostname(hostname):
        raise SSRFBlockedError(f"Blocked hostname: {hostname}")

    # Check if hostname is already an IP literal
    if _is_private_ip(hostname):
        raise SSRFBlockedError(f"Blocked: private/internal IP address ({hostname})")

    # Resolve hostname and check all resulting IPs
    try:
        addrinfos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFBlockedError(f"DNS resolution failed for {hostname}: {e}") from e

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = str(sockaddr[0])
        if _is_benchmark_ip(ip):
            continue
        if _is_private_ip(ip):
            raise SSRFBlockedError(f"Blocked: {hostname} resolves to private IP ({ip})")
