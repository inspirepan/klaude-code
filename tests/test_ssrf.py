from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from klaude_code.core.tool.web.ssrf import (
    SSRFBlockedError,
    _is_blocked_hostname,  # pyright: ignore[reportPrivateUsage]
    _is_private_ip,  # pyright: ignore[reportPrivateUsage]
    check_ssrf,
)


class TestIsPrivateIp:
    def test_loopback_v4(self) -> None:
        assert _is_private_ip("127.0.0.1") is True

    def test_loopback_v6(self) -> None:
        assert _is_private_ip("::1") is True

    def test_private_10(self) -> None:
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("10.255.255.255") is True

    def test_private_172(self) -> None:
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("172.31.255.255") is True

    def test_private_192(self) -> None:
        assert _is_private_ip("192.168.0.1") is True
        assert _is_private_ip("192.168.255.255") is True

    def test_link_local(self) -> None:
        assert _is_private_ip("169.254.169.254") is True
        assert _is_private_ip("169.254.0.1") is True

    def test_public_ip(self) -> None:
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False
        assert _is_private_ip("93.184.216.34") is False

    def test_unparseable(self) -> None:
        assert _is_private_ip("not-an-ip") is False

    def test_unspecified_v4(self) -> None:
        assert _is_private_ip("0.0.0.0") is True

    def test_unspecified_v6(self) -> None:
        assert _is_private_ip("::") is True

    def test_link_local_v6(self) -> None:
        assert _is_private_ip("fe80::1") is True

    def test_public_v6(self) -> None:
        assert _is_private_ip("2607:f8b0:4004:800::200e") is False


class TestIsBlockedHostname:
    def test_localhost(self) -> None:
        assert _is_blocked_hostname("localhost") is True

    def test_localhost_subdomain(self) -> None:
        assert _is_blocked_hostname("foo.localhost") is True

    def test_metadata_google(self) -> None:
        assert _is_blocked_hostname("metadata.google.internal") is True

    def test_dot_local(self) -> None:
        assert _is_blocked_hostname("myservice.local") is True

    def test_dot_internal(self) -> None:
        assert _is_blocked_hostname("db.internal") is True

    def test_normal_domain(self) -> None:
        assert _is_blocked_hostname("example.com") is False
        assert _is_blocked_hostname("google.com") is False

    def test_case_insensitive(self) -> None:
        assert _is_blocked_hostname("LOCALHOST") is True
        assert _is_blocked_hostname("Metadata.Google.Internal") is True

    def test_trailing_dot(self) -> None:
        assert _is_blocked_hostname("localhost.") is True


class TestCheckSsrf:
    def test_no_hostname(self) -> None:
        with pytest.raises(SSRFBlockedError, match="No hostname"):
            check_ssrf("http://")

    def test_blocked_hostname_localhost(self) -> None:
        with pytest.raises(SSRFBlockedError, match="Blocked hostname"):
            check_ssrf("http://localhost/admin")

    def test_blocked_hostname_metadata(self) -> None:
        with pytest.raises(SSRFBlockedError, match="Blocked hostname"):
            check_ssrf("http://metadata.google.internal/computeMetadata/v1/")

    def test_ip_literal_private(self) -> None:
        with pytest.raises(SSRFBlockedError, match="private/internal IP"):
            check_ssrf("http://127.0.0.1:8080/secret")

    def test_ip_literal_link_local(self) -> None:
        with pytest.raises(SSRFBlockedError, match="private/internal IP"):
            check_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_ip_literal_rfc1918(self) -> None:
        with pytest.raises(SSRFBlockedError, match="private/internal IP"):
            check_ssrf("http://10.0.0.1/internal")

    def test_dns_resolves_to_private(self) -> None:
        fake_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
        with (
            patch("klaude_code.core.tool.web.ssrf.socket.getaddrinfo", return_value=fake_addrinfo),
            pytest.raises(SSRFBlockedError, match="resolves to private IP"),
        ):
            check_ssrf("http://evil.example.com/")

    def test_dns_resolves_to_public(self) -> None:
        fake_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
        with patch("klaude_code.core.tool.web.ssrf.socket.getaddrinfo", return_value=fake_addrinfo):
            check_ssrf("http://example.com/")  # should not raise

    def test_dns_failure(self) -> None:
        with (
            patch("klaude_code.core.tool.web.ssrf.socket.getaddrinfo", side_effect=socket.gaierror("DNS failed")),
            pytest.raises(SSRFBlockedError, match="DNS resolution failed"),
        ):
            check_ssrf("http://nonexistent.example.com/")
