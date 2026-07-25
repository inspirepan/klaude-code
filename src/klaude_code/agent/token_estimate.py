"""Local token estimation.

There is no token-counting API available here, so token counts are estimated from text.
A flat ``chars / 4`` is close enough for English prose but wrong in two ways that matter:

- CJK text costs roughly one token per character, so ``chars / 4`` underestimates it ~3x.
- Code, JSON, and absolute paths are punctuation-dense and land nearer 3 chars/token.

So characters are weighted by script instead. The result is still an estimate; when a real
API usage report exists, prefer calibrating against it (see ``agent/context_usage.py``).
"""

from __future__ import annotations

# Roughly one token per CJK character; Claude's tokenizer lands a little under 1.
_CJK_TOKENS_PER_CHAR = 0.7
# Latin text averages ~3.8 chars/token across prose and punctuation-dense code.
_LATIN_CHARS_PER_TOKEN = 3.8

# CJK ideographs, kana, hangul, and fullwidth/CJK punctuation.
_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3000, 0x303F),  # CJK symbols and punctuation
    (0x3040, 0x30FF),  # hiragana + katakana
    (0x3400, 0x4DBF),  # CJK unified ideographs extension A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xAC00, 0xD7AF),  # hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFF00, 0xFFEF),  # halfwidth and fullwidth forms
)

# Every message carries role and structural framing on the wire beyond its text.
MESSAGE_OVERHEAD_TOKENS = 4

# A single image is billed well above its textual footprint; mirrors the compaction default.
IMAGE_TOKENS = 1600


def _is_cjk(char: str) -> bool:
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in _CJK_RANGES)


def estimate_text_tokens(text: str) -> int:
    """Estimate the token count of ``text``, weighting CJK characters separately."""
    if not text:
        return 0

    cjk_chars = sum(1 for char in text if _is_cjk(char))
    latin_chars = len(text) - cjk_chars
    estimated = cjk_chars * _CJK_TOKENS_PER_CHAR + latin_chars / _LATIN_CHARS_PER_TOKEN
    return max(1, round(estimated))
