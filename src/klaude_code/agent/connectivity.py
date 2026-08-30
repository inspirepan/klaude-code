"""Transport-level error classification for the step retry policy.

A step that fails because the endpoint was never reached says nothing about the
request: the machine is suspended, the link is down, or DNS is gone. Those
failures are kept out of the bounded step-retry budget, unlike API-level errors
(5xx, 429, quota) which prove the endpoint answered.
"""

# Provider adapters build stream errors as f"{exception_class_name} {exception}"
# (see llm/*/client.py), so class names are matched alongside message text.
_CONNECTIVITY_MARKERS = (
    # openai / anthropic SDK wrappers around any httpx transport failure
    "apiconnectionerror",
    "apitimeouterror",
    # httpx
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "writetimeout",
    "pooltimeout",
    "readerror",
    "writeerror",
    "remoteprotocolerror",
    "proxyerror",
    # botocore
    "endpointconnectionerror",
    "connectionclosederror",
    # stdlib socket / DNS
    "connectionreseterror",
    "connectionrefusederror",
    "connectionabortederror",
    "gaierror",
    "server disconnected",
    "connection reset by peer",
    "network is unreachable",
    "no route to host",
    "temporary failure in name resolution",
    "nodename nor servname provided",
)


def is_connectivity_error(error_message: str | None) -> bool:
    """Return True when the failure means the endpoint could not be reached."""

    if not error_message:
        return False
    text = error_message.casefold()
    return any(marker in text for marker in _CONNECTIVITY_MARKERS)
