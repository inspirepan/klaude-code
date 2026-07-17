"""Kitty keyboard protocol (CSI u) tolerance for the REPL input.

Some programs push kitty keyboard-protocol flags onto the terminal and fail
to pop them (crashed TUI apps, fish 4 line editor, another leaked CLI). The
terminal then encodes modified keys as ``CSI <codepoint>;<modifiers> u``
instead of legacy C0 bytes: Ctrl+W arrives as ``\\x1b[119;5u``.

prompt_toolkit's vt100 parser does not know these sequences. Its fallback
emits a bare Escape key press — which the REPL binds to "interrupt the
running task" — followed by the sequence body as literal text. One stray
Ctrl+W then aborts the running task and leaves ``[119;5u`` in the input
buffer.

Two defenses, both installed by :class:`PromptToolkitInput`:

* :func:`install_csi_u_sequences` teaches the parser the common CSI-u
  encodings by extending ``ANSI_SEQUENCES``, so those keys resolve to their
  normal prompt_toolkit keys and key-release events are ignored.
* :data:`KITTY_KEYBOARD_RESET` is written to the terminal at REPL start to
  clear any leaked flags (terminals without kitty protocol ignore it).

Values must be ``Keys`` members (or tuples of them), never plain characters:
the parser passes the raw matched sequence as ``KeyPress.data``, and the
self-insert binding inserts ``event.data`` verbatim.
"""

from __future__ import annotations

from typing import cast

from prompt_toolkit.input import ansi_escape_sequences
from prompt_toolkit.keys import Keys

# Set the current kitty keyboard-protocol flags to 0 ("legacy" encoding).
# CSI = <flags> ; 1 u — mode 1 replaces all flag bits of the current entry.
KITTY_KEYBOARD_RESET = "\x1b[=0;1u"

_installed = False

_KeyValue = Keys | tuple[Keys | str, ...]


def _base_key(code: int, *, shift: bool, ctrl: bool) -> Keys | None:
    """Return the prompt_toolkit key for a CSI-u codepoint, or None."""
    if code == 27:
        return Keys.Escape
    if code == 13:
        return Keys.ControlM
    if code == 9:
        return Keys.BackTab if shift else Keys.ControlI
    if code == 127:
        return Keys.ControlH
    if code == 32 and ctrl:
        return Keys.ControlAt
    ch = chr(code)
    if "a" <= ch <= "z" and ctrl:
        return Keys(f"c-{ch}")
    if "0" <= ch <= "9" and ctrl:
        return Keys(f"c-s-{ch}") if shift else Keys(f"c-{ch}")
    return None


def _build_sequences() -> dict[str, _KeyValue]:
    sequences: dict[str, _KeyValue] = {}
    codes = [9, 13, 27, 32, 127, *range(ord("a"), ord("z") + 1), *range(ord("0"), ord("9") + 1)]
    for code in codes:
        for modifier in range(1, 9):  # 1 + bitmask(shift=1, alt=2, ctrl=4)
            bits = modifier - 1
            shift = bool(bits & 1)
            alt = bool(bits & 2)
            ctrl = bool(bits & 4)

            base: Keys | str | None = _base_key(code, shift=shift, ctrl=ctrl)
            if base is None and alt:
                # Alt-only chords have no dedicated Keys member; emit the
                # escape-prefixed form the key processor already understands.
                # The character element carries no data payload, so unbound
                # combos are a no-op instead of inserting garbage.
                base = chr(code)
            if base is None:
                continue
            key: _KeyValue = (Keys.Escape, base) if alt and code != 27 else cast(_KeyValue, base)

            base_form = f"\x1b[{code};{modifier}"
            for suffix in ("u", ":1u", ":2u"):  # press / explicit-press / repeat
                sequences[base_form + suffix] = key
            sequences[base_form + ":3u"] = Keys.Ignore  # key release

        bare = _base_key(code, shift=False, ctrl=False)
        if bare is not None:
            sequences[f"\x1b[{code}u"] = bare
    return sequences


def install_csi_u_sequences() -> None:
    """Extend prompt_toolkit's ANSI_SEQUENCES with kitty CSI-u encodings.

    Idempotent; never overrides sequences prompt_toolkit already defines.
    """
    global _installed
    if _installed:
        return
    _installed = True
    # The declared value type is ``Keys | tuple[Keys, ...]``; the parser's
    # _call_handler also accepts plain characters inside tuples (it feeds
    # each element as its own KeyPress).
    table = cast("dict[str, object]", ansi_escape_sequences.ANSI_SEQUENCES)
    for sequence, key in _build_sequences().items():
        table.setdefault(sequence, key)
