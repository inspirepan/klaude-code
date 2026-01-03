"""Monkey-patch Rich wrapping for better CJK line breaks."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable


def _is_cjk_char(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _contains_cjk(text: str) -> bool:
    return any(_is_cjk_char(ch) for ch in text)


def _is_ascii_word_char(ch: str) -> bool:
    o = ord(ch)
    return (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122) or ch in "_."


def _find_prefix_len_for_remaining(word: str, remaining_space: int) -> int:
    """Find a prefix length (in chars) that fits remaining_space.

    This prefers breakpoints that don't split ASCII word-like runs.
    """

    if remaining_space <= 0:
        return 0

    # Local import keeps import-time overhead low.
    from rich.cells import get_character_cell_size

    total = 0
    best = 0
    n = len(word)

    for i, ch in enumerate(word):
        total += get_character_cell_size(ch)
        if total > remaining_space:
            break

        boundary = i + 1
        if boundary >= n:
            best = boundary
            break

        # Avoid leaving a path separator at the start of the next line.
        if word[boundary] in "/":
            continue

        # Disallow breaks inside ASCII word runs: ...a|b...
        if _is_ascii_word_char(word[boundary - 1]) and _is_ascii_word_char(word[boundary]):
            continue

        best = boundary

    return best


_rich_cjk_wrap_patch_installed = False


def install_rich_cjk_wrap_patch() -> bool:
    """Install a monkey-patch that improves CJK line wrapping in Rich.

    Rich wraps text by tokenizing on whitespace, which causes long CJK runs to be
    treated as a single "word" and moved to the next line wholesale.

    This patch keeps ASCII word wrapping behaviour intact, but allows breaking
    CJK-containing tokens at the end of a line to fill remaining space.

    Returns:
        True if the patch was installed in this process.
    """

    global _rich_cjk_wrap_patch_installed
    if _rich_cjk_wrap_patch_installed:
        return False

    import rich._wrap as _wrap
    import rich.text as _text
    from rich._loop import loop_last
    from rich.cells import cell_len, chop_cells

    _OPEN_TO_CLOSE = {
        "(": ")",
        "（": "）",
        "[": "]",
        "{": "}",
        "“": "”",
        "‘": "’",
        "《": "》",
        "〈": "〉",
        "「": "」",
        "『": "』",
        "【": "】",
    }

    def _leading_unclosed_delim(word: str) -> str | None:
        stripped = word.lstrip()
        if not stripped:
            return None

        close_delim = _OPEN_TO_CLOSE.get(stripped[0])
        if close_delim is None:
            return None

        if close_delim in stripped:
            return None

        return close_delim

    def _close_delim_appears_soon(
        word_tokens: list[str],
        *,
        start_index: int,
        close_delim: str,
        max_chars: int = 32,
        max_tokens: int = 4,
    ) -> bool:
        consumed = 0
        for token in word_tokens[start_index + 1 : start_index + 1 + max_tokens]:
            if not token:
                continue

            close_pos = token.find(close_delim)
            if close_pos != -1 and (consumed + close_pos) < max_chars:
                return True

            consumed += len(token)
            if consumed >= max_chars:
                return False

        return False

    def divide_line_patched(text: str, width: int, fold: bool = True) -> list[int]:
        break_positions: list[int] = []

        def append(pos: int) -> None:
            if pos and (not break_positions or break_positions[-1] != pos):
                break_positions.append(pos)

        cell_offset = 0
        _cell_len: Callable[[str], int] = cell_len

        words = list(_wrap.words(text))
        word_tokens = [w for _s, _e, w in words]

        for index, (start, _end, word) in enumerate(words):
            next_word: str | None = None
            if index + 1 < len(words):
                next_word = words[index + 1][2]

            # Heuristic: avoid leaving an unclosed opening delimiter fragment (e.g. "(Deep ")
            # at the end of a line when the next token will wrap.
            word_length = _cell_len(word.rstrip())
            remaining_space = width - cell_offset
            if remaining_space >= word_length and cell_offset and start and next_word is not None:
                cell_offset_with_trailing = cell_offset + _cell_len(word)
                next_length = _cell_len(next_word.rstrip())
                next_will_wrap = next_length > width or (width - cell_offset_with_trailing) < next_length

                close_delim = _leading_unclosed_delim(word)
                if close_delim is not None and next_will_wrap:
                    stripped = word.strip()
                    if _cell_len(stripped) <= 16 and _close_delim_appears_soon(
                        word_tokens, start_index=index, close_delim=close_delim
                    ):
                        append(start)
                        cell_offset = _cell_len(word)
                        continue

            while True:
                word_length = _cell_len(word.rstrip())
                remaining_space = width - cell_offset

                if remaining_space >= word_length:
                    cell_offset += _cell_len(word)
                    break

                # Prefer splitting CJK-containing tokens to fill remaining space.
                if fold and cell_offset and start and remaining_space > 0 and _contains_cjk(word):
                    prefix_len = _find_prefix_len_for_remaining(word, remaining_space)
                    if prefix_len:
                        break_at = start + prefix_len
                        append(break_at)
                        word = word[prefix_len:]
                        start = break_at

                        # If the remainder fits on the next (empty) line, keep Rich's
                        # existing behaviour and move on.
                        if _cell_len(word.rstrip()) <= width:
                            cell_offset = _cell_len(word)
                            break

                        # Otherwise, continue folding the remainder starting on a new line.
                        cell_offset = 0
                        continue

                # Fall back to Rich's original logic.
                if word_length > width:
                    if fold:
                        folded_word = chop_cells(word, width=width)
                        for last, line in loop_last(folded_word):
                            if start:
                                append(start)
                            if last:
                                cell_offset = _cell_len(line)
                            else:
                                start += len(line)
                    else:
                        if start:
                            append(start)
                        cell_offset = _cell_len(word)
                    break

                if cell_offset and start:
                    append(start)
                    cell_offset = _cell_len(word)
                break

        return break_positions

    _wrap.divide_line = divide_line_patched  # pyright: ignore[reportPrivateImportUsage]
    _text.divide_line = divide_line_patched  # pyright: ignore[reportPrivateImportUsage]
    _rich_cjk_wrap_patch_installed = True
    return True
