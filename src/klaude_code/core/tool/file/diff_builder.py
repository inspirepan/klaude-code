from __future__ import annotations

import difflib
from typing import cast

from diff_match_patch import diff_match_patch  # type: ignore[import-untyped]

from klaude_code.protocol import model

_MAX_LINE_LENGTH_FOR_CHAR_DIFF = 2000
_DEFAULT_CONTEXT_LINES = 3


def build_structured_diff(before: str, after: str, *, file_path: str) -> model.DiffUIExtra:
    """Build a structured diff with char-level spans for a single file."""
    file_diff = _build_file_diff(before, after, file_path=file_path)
    return model.DiffUIExtra(files=[file_diff])


def build_structured_file_diff(before: str, after: str, *, file_path: str) -> model.DiffFileDiff:
    """Build a structured diff for a single file."""
    return _build_file_diff(before, after, file_path=file_path)


def _build_file_diff(before: str, after: str, *, file_path: str) -> model.DiffFileDiff:
    before_lines = _split_lines(before)
    after_lines = _split_lines(after)

    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    lines: list[model.DiffLine] = []
    stats_add = 0
    stats_remove = 0

    grouped_opcodes = matcher.get_grouped_opcodes(n=_DEFAULT_CONTEXT_LINES)
    for group_idx, group in enumerate(grouped_opcodes):
        if group_idx > 0:
            lines.append(_gap_line())

        # Anchor line numbers to the actual start of the displayed hunk in the "after" file.
        new_line_no = group[0][3] + 1

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in after_lines[j1:j2]:
                    lines.append(_ctx_line(line, new_line_no))
                    new_line_no += 1
            elif tag == "delete":
                for line in before_lines[i1:i2]:
                    lines.append(_remove_line([model.DiffSpan(op="equal", text=line)]))
                    stats_remove += 1
            elif tag == "insert":
                for line in after_lines[j1:j2]:
                    lines.append(_add_line([model.DiffSpan(op="equal", text=line)], new_line_no))
                    stats_add += 1
                    new_line_no += 1
            elif tag == "replace":
                old_block = before_lines[i1:i2]
                new_block = after_lines[j1:j2]
                max_len = max(len(old_block), len(new_block))
                for idx in range(max_len):
                    old_line = old_block[idx] if idx < len(old_block) else None
                    new_line = new_block[idx] if idx < len(new_block) else None
                    if old_line is not None and new_line is not None:
                        remove_spans, add_spans = _diff_line_spans(old_line, new_line)
                        lines.append(_remove_line(remove_spans))
                        lines.append(_add_line(add_spans, new_line_no))
                        stats_remove += 1
                        stats_add += 1
                        new_line_no += 1
                    elif old_line is not None:
                        lines.append(_remove_line([model.DiffSpan(op="equal", text=old_line)]))
                        stats_remove += 1
                    elif new_line is not None:
                        lines.append(_add_line([model.DiffSpan(op="equal", text=new_line)], new_line_no))
                        stats_add += 1
                        new_line_no += 1

    return model.DiffFileDiff(
        file_path=file_path,
        lines=lines,
        stats_add=stats_add,
        stats_remove=stats_remove,
    )


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return text.splitlines()


def _ctx_line(text: str, new_line_no: int) -> model.DiffLine:
    return model.DiffLine(
        kind="ctx",
        new_line_no=new_line_no,
        spans=[model.DiffSpan(op="equal", text=text)],
    )


def _gap_line() -> model.DiffLine:
    return model.DiffLine(
        kind="gap",
        new_line_no=None,
        spans=[model.DiffSpan(op="equal", text="")],
    )


def _add_line(spans: list[model.DiffSpan], new_line_no: int) -> model.DiffLine:
    return model.DiffLine(kind="add", new_line_no=new_line_no, spans=_ensure_spans(spans))


def _remove_line(spans: list[model.DiffSpan]) -> model.DiffLine:
    return model.DiffLine(kind="remove", new_line_no=None, spans=_ensure_spans(spans))


def _ensure_spans(spans: list[model.DiffSpan]) -> list[model.DiffSpan]:
    if spans:
        return spans
    return [model.DiffSpan(op="equal", text="")]


def _diff_line_spans(old_line: str, new_line: str) -> tuple[list[model.DiffSpan], list[model.DiffSpan]]:
    if not _should_char_diff(old_line, new_line):
        return (
            [model.DiffSpan(op="equal", text=old_line)],
            [model.DiffSpan(op="equal", text=new_line)],
        )

    differ = diff_match_patch()
    diffs = cast(list[tuple[int, str]], differ.diff_main(old_line, new_line))  # type: ignore[no-untyped-call]
    differ.diff_cleanupSemantic(diffs)  # type: ignore[no-untyped-call]

    remove_spans: list[model.DiffSpan] = []
    add_spans: list[model.DiffSpan] = []

    for op, text in diffs:
        if not text:
            continue
        if op == diff_match_patch.DIFF_EQUAL:  # type: ignore[no-untyped-call]
            remove_spans.append(model.DiffSpan(op="equal", text=text))
            add_spans.append(model.DiffSpan(op="equal", text=text))
        elif op == diff_match_patch.DIFF_DELETE:  # type: ignore[no-untyped-call]
            remove_spans.append(model.DiffSpan(op="delete", text=text))
        elif op == diff_match_patch.DIFF_INSERT:  # type: ignore[no-untyped-call]
            add_spans.append(model.DiffSpan(op="insert", text=text))

    return _ensure_spans(remove_spans), _ensure_spans(add_spans)


def _should_char_diff(old_line: str, new_line: str) -> bool:
    return len(old_line) <= _MAX_LINE_LENGTH_FOR_CHAR_DIFF and len(new_line) <= _MAX_LINE_LENGTH_FOR_CHAR_DIFF
