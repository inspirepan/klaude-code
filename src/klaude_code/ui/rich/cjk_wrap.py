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
    return (
        (48 <= o <= 57)
        or (65 <= o <= 90)
        or (97 <= o <= 122)
        or ch in "_."
    )


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

    def divide_line_patched(text: str, width: int, fold: bool = True) -> list[int]:
        break_positions: list[int] = []
        append = break_positions.append

        cell_offset = 0
        _cell_len: Callable[[str], int] = cell_len

        for start, _end, word in _wrap.words(text):
            word_length = _cell_len(word.rstrip())
            remaining_space = width - cell_offset

            if remaining_space >= word_length:
                cell_offset += _cell_len(word)
                continue

            # Special-case: if the token would fit on an empty line but doesn't fit
            # on the current line, allow breaking within it when it contains CJK.
            if (
                fold
                and cell_offset
                and start
                and remaining_space > 0
                and word_length <= width
                and _contains_cjk(word)
            ):
                prefix_len = _find_prefix_len_for_remaining(word, remaining_space)
                if prefix_len:
                    break_at = start + prefix_len
                    if break_at:
                        append(break_at)
                    rest = word[prefix_len:]
                    cell_offset = _cell_len(rest)
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
            elif cell_offset and start:
                append(start)
                cell_offset = _cell_len(word)

        return break_positions

    setattr(_wrap, "divide_line", divide_line_patched)
    setattr(_text, "divide_line", divide_line_patched)
    _rich_cjk_wrap_patch_installed = True
    return True
