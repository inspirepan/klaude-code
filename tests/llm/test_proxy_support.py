from __future__ import annotations

from klaude_code.llm.proxy_support import configured_socks_proxy_var, is_missing_socks_proxy_support_error


def test_configured_socks_proxy_var_detects_socks_proxy_without_returning_value() -> None:
    env = {
        "HTTPS_PROXY": "socks5://user:secret@127.0.0.1:1080",
    }

    assert configured_socks_proxy_var(env) == "HTTPS_PROXY"


def test_configured_socks_proxy_var_ignores_http_proxy() -> None:
    env = {
        "HTTPS_PROXY": "http://127.0.0.1:7890",
    }

    assert configured_socks_proxy_var(env) is None


def test_is_missing_socks_proxy_support_error_detects_httpx_message() -> None:
    exc = ImportError("Using SOCKS proxy, but the 'socksio' package is not installed.")

    assert is_missing_socks_proxy_support_error(exc)


def test_is_missing_socks_proxy_support_error_walks_exception_chain() -> None:
    root = ImportError("python-socks is required to use a SOCKS proxy")

    try:
        raise RuntimeError("client init failed") from root
    except RuntimeError as exc:
        assert is_missing_socks_proxy_support_error(exc)