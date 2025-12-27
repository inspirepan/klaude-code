from __future__ import annotations

from collections.abc import Iterable, Sequence


class SearchableFormattedText:
    """
    Wrapper for prompt_toolkit formatted text that also supports string-like
    methods commonly expected by search filters (e.g., ``.lower()``).

    - ``fragments``: A sequence of (style, text) tuples accepted by
      prompt_toolkit's ``to_formatted_text``.
    - ``plain``: Optional plain text for searching. If omitted, it is derived by
      concatenating the text parts of the fragments.
    """

    def __init__(self, fragments: Sequence[tuple[str, str]], plain: str | None = None):
        self._fragments: list[tuple[str, str]] = list(fragments)
        if plain is None:
            plain = "".join(text for _, text in self._fragments)
        self._plain = plain

    # Recognized by prompt_toolkit's to_formatted_text(value)
    def __pt_formatted_text__(
        self,
    ) -> Iterable[tuple[str, str]]:  # pragma: no cover - passthrough
        return self._fragments

    # Provide a human-readable representation.
    def __str__(self) -> str:  # pragma: no cover - utility
        return self._plain

    # Minimal string API for search filtering.
    def lower(self) -> str:
        return self._plain.lower()

    def upper(self) -> str:  # pragma: no cover - convenience
        return self._plain.upper()

    # Expose the plain text if needed elsewhere.
    @property
    def plain(self) -> str:
        return self._plain


class SearchableFormattedList(list[tuple[str, str]]):
    """
    List variant compatible with prompt_toolkit formatted-text usage.

    - Behaves like ``List[Tuple[str, str]]`` for rendering (so ``isinstance(..., list)`` works).
    - Provides ``.lower()``/``.upper()`` returning the plain text for search filtering.
    """

    def __init__(self, fragments: Sequence[tuple[str, str]], plain: str | None = None):
        super().__init__(fragments)
        if plain is None:
            plain = "".join(text for _, text in fragments)
        self._plain = plain

    def lower(self) -> str:
        return self._plain.lower()

    def upper(self) -> str:  # pragma: no cover - convenience
        return self._plain.upper()

    @property
    def plain(self) -> str:
        return self._plain
