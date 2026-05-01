from __future__ import annotations

import re

# Allow inline @ and / tokens after CJK text so users typing Chinese or
# Japanese do not need to insert an extra space before the trigger character.
# Keep English-word boundaries unchanged to avoid matching emails or URLs.
CJK_INLINE_BOUNDARY_CHARS = (
    r"\u3005-\u3007"
    r"\u303b"
    r"\u3040-\u309f"
    r"\u30a0-\u30ff"
    r"\u31f0-\u31ff"
    r"\u3400-\u4dbf"
    r"\u4e00-\u9fff"
    r"\uf900-\ufaff"
    r"\uff66-\uff9f"
)
INLINE_TOKEN_BOUNDARY = rf"(^|[\s{CJK_INLINE_BOUNDARY_CHARS}])"

# Characters that terminate an @-path token besides whitespace.
# Includes CJK punctuation and fullwidth ASCII punctuation so that a path
# followed by e.g. Chinese "，" or "。" is not treated as part of the path.
# Fullwidth digits/letters and halfwidth katakana are intentionally excluded
# to keep them usable within paths.
AT_TOKEN_STOP_CHARS = (
    r"\u3000-\u303f"  # CJK symbols and punctuation (、。「」『』《》【】 ...)
    r"\uff01-\uff0f"  # fullwidth ASCII punctuation (！＂＃＄％＆＇（）＊＋，－．／)
    r"\uff1a-\uff20"  # ：；＜＝＞？＠
    r"\uff3b-\uff40"  # ［＼］＾＿｀
    r"\uff5b-\uff65"  # ｛｜｝～｡｢｣､･ ...
)

# Pattern to match @token for completion refresh. Supports both plain tokens
# like `@src/file.py` and quoted tokens like `@"path with spaces/file.py"`.
AT_COMPLETION_PATTERN = re.compile(rf'{INLINE_TOKEN_BOUNDARY}@(?P<frag>"[^"]*"|[^\s{AT_TOKEN_STOP_CHARS}]*)$')

# Pattern to match inline /skill token for skill completion.
SKILL_COMPLETION_PATTERN = re.compile(rf"{INLINE_TOKEN_BOUNDARY}(?P<prefix>//|/)(?P<frag>[^\s/]*)$")

# Match @ preceded by whitespace, start of line, CJK text, or -> (ReadTool
# line number arrow). Supports optional line range suffix in consumers:
# @file.txt#L10-20 or @file.txt#L10.
AT_FILE_PATTERN = re.compile(
    rf'(?P<boundary>{INLINE_TOKEN_BOUNDARY}|(?<=\u2192))'
    rf'(?P<at_token>@("(?P<quoted>[^"]+)"|(?P<plain>[^\s{AT_TOKEN_STOP_CHARS}]+)))'
)

# Match inline patterns for user-message rendering. Group "token" captures the
# visual token without the leading boundary. Group "skill_token" captures one of:
# - /skill:skill-name
# - //skill:skill-name
INLINE_RENDER_PATTERN = re.compile(
    rf'(?P<boundary>{INLINE_TOKEN_BOUNDARY})'
    rf'(?P<token>@(?:"[^"]+"|[^\s{AT_TOKEN_STOP_CHARS}]+)'
    rf'|(?P<skill_token>//skill:[^\s/]+(?=\s|$)|/skill:[^\s/]+(?=\s|$)))'
)
