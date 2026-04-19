import re

_OVERFLOW_PATTERNS = [
    re.compile(r"prompt is too long", re.IGNORECASE),
    re.compile(r"exceeds the context window", re.IGNORECASE),
    re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE),
    re.compile(r"maximum prompt length is \d+", re.IGNORECASE),
    re.compile(r"reduce the length of the messages", re.IGNORECASE),
    re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE),
    re.compile(r"exceeds the limit of \d+", re.IGNORECASE),
    re.compile(r"exceeds the available context size", re.IGNORECASE),
    re.compile(r"greater than the context length", re.IGNORECASE),
    re.compile(r"context length exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"token limit exceeded", re.IGNORECASE),
]

_STATUS_CODE_PATTERN = re.compile(r"^4(00|13|29)\s*(status code)?\s*\(no body\)", re.IGNORECASE)


def is_context_overflow(error_message: str | None) -> bool:
    if not error_message:
        return False
    if _STATUS_CODE_PATTERN.search(error_message):
        return True
    return any(pattern.search(error_message) for pattern in _OVERFLOW_PATTERNS)
