"""Consume variable-length OSC 7501 replies inside prompt-toolkit's parser."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import override

from prompt_toolkit.input.vt100_parser import Vt100Parser, _Flush

_PREFIX = "\x1b]7501;"


class ProgramStatusParser(Vt100Parser):
    def __init__(self, parser: Vt100Parser, on_reply: Callable[[str], None]) -> None:
        self._on_reply = on_reply
        super().__init__(parser.feed_key_callback)

    @override
    def _input_parser_generator(self) -> Generator[None, str | _Flush]:
        normal = super()._input_parser_generator()
        next(normal)
        pending = ""
        while True:
            char = yield
            if isinstance(char, _Flush):
                # Once the OSC header is complete, retain split replies across
                # prompt-toolkit's escape timeout. Other escapes keep their semantics.
                if pending.startswith(_PREFIX) and pending[len(_PREFIX) :].lstrip(" \t").startswith("?"):
                    continue
                for item in pending:
                    normal.send(item)
                pending = ""
                normal.send(char)
                continue
            pending += char
            if _PREFIX.startswith(pending):
                continue
            if pending.startswith(_PREFIX):
                body = pending[len(_PREFIX) :].lstrip(" \t")
                if body.startswith("?") and pending.endswith(("\x07", "\x1b\\")):
                    self._on_reply(pending)
                    pending = ""
                    continue
                if (
                    (not body or body.startswith("?"))
                    and len(pending) <= 8192
                    and all(c >= " " or c in "\x1b\t" for c in body)
                ):
                    continue
            # Forward non-replies unchanged, including normal keys and pastes.
            for item in pending:
                normal.send(item)
            pending = ""
