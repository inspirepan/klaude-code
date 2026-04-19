from __future__ import annotations

import difflib
from typing import cast

from diff_match_patch import diff_match_patch  # type: ignore[import-untyped]

from klaude_code.const import DIFF_DEFAULT_CONTEXT_LINES, DIFF_MAX_LINE_LENGTH_FOR_CHAR_DIFF
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffSpan, DiffUIExtra


def build_structured_diff(before: str, after: str, *, file_path: str) -> DiffUIExtra:
    """Build a structured diff with char-level spans for a single file."""
    file_diff = _build_file_diff(before, after, file_path=file_path)
    raw_unified_diff = build_unified_diff_text(before, after, from_file=file_path)
    return DiffUIExtra(files=[file_diff], raw_unified_diff=raw_unified_diff)

def build_structured_file_diff(before: str, after: str, *, file_path: str) -> DiffFileDiff:
    """Build a structured diff for a single file."""
    return _build_file_diff(before, after, file_path=file_path)

def build_unified_diff_text(before: str, after: str, *, from_file: str, to_file: str | None = None) -> str:
    """Build raw unified diff text using default context lines."""
    target_file = to_file if to_file is not None else from_file
    lines = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=from_file,
        tofile=target_file,
        n=DIFF_DEFAULT_CONTEXT_LINES,
        lineterm="",
    )
    return "\n".join(lines)

def _build_file_diff(before: str, after: str, *, file_path: str) -> DiffFileDiff:
    before_lines = _split_lines(before)
    after_lines = _split_lines(after)

    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    lines: list[DiffLine] = []
    stats_add = 0
    stats_remove = 0

    grouped_opcodes = matcher.get_grouped_opcodes(n=DIFF_DEFAULT_CONTEXT_LINES)
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
                    lines.append(_remove_line([DiffSpan(op="equal", text=line)]))
                    stats_remove += 1
            elif tag == "insert":
                for line in after_lines[j1:j2]:
                    lines.append(_add_line([DiffSpan(op="equal", text=line)], new_line_no))
                    stats_add += 1
                    new_line_no += 1
            elif tag == "replace":
                old_block = before_lines[i1:i2]
                new_block = after_lines[j1:j2]

                # Emit replacement blocks in unified-diff style: all removals first, then all additions.
                # This matches VSCode's readability (--- then +++), while keeping per-line char spans.
                remove_block: list[list[DiffSpan]] = []
                add_block: list[list[DiffSpan]] = []

                paired_len = min(len(old_block), len(new_block))
                for idx in range(paired_len):
                    remove_spans, add_spans = _diff_line_spans(old_block[idx], new_block[idx])
                    remove_block.append(remove_spans)
                    add_block.append(add_spans)

                for old_line in old_block[paired_len:]:
                    remove_block.append([DiffSpan(op="equal", text=old_line)])
                for new_line in new_block[paired_len:]:
                    add_block.append([DiffSpan(op="equal", text=new_line)])

                for spans in remove_block:
                    lines.append(_remove_line(spans))
                    stats_remove += 1

                for spans in add_block:
                    lines.append(_add_line(spans, new_line_no))
                    stats_add += 1
                    new_line_no += 1

    return DiffFileDiff(
        file_path=file_path,
        lines=lines,
        stats_add=stats_add,
        stats_remove=stats_remove,
    )

def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return text.splitlines()

def _ctx_line(text: str, new_line_no: int) -> DiffLine:
    return DiffLine(
        kind="ctx",
        new_line_no=new_line_no,
        spans=[DiffSpan(op="equal", text=text)],
    )

def _gap_line() -> DiffLine:
    return DiffLine(
        kind="gap",
        new_line_no=None,
        spans=[DiffSpan(op="equal", text="")],
    )

def _add_line(spans: list[DiffSpan], new_line_no: int) -> DiffLine:
    return DiffLine(kind="add", new_line_no=new_line_no, spans=_ensure_spans(spans))

def _remove_line(spans: list[DiffSpan]) -> DiffLine:
    return DiffLine(kind="remove", new_line_no=None, spans=_ensure_spans(spans))

def _ensure_spans(spans: list[DiffSpan]) -> list[DiffSpan]:
    if spans:
        return spans
    return [DiffSpan(op="equal", text="")]

def _diff_line_spans(old_line: str, new_line: str) -> tuple[list[DiffSpan], list[DiffSpan]]:
    if not _should_char_diff(old_line, new_line):
        return (
            [DiffSpan(op="equal", text=old_line)],
            [DiffSpan(op="equal", text=new_line)],
        )

    differ = diff_match_patch()
    diffs = cast(list[tuple[int, str]], differ.diff_main(old_line, new_line))  # type: ignore[no-untyped-call]
    differ.diff_cleanupSemantic(diffs)  # type: ignore[no-untyped-call]

    remove_spans: list[DiffSpan] = []
    add_spans: list[DiffSpan] = []

    for op, text in diffs:
        if not text:
            continue
        if op == diff_match_patch.DIFF_EQUAL:  # type: ignore[no-untyped-call]
            remove_spans.append(DiffSpan(op="equal", text=text))
            add_spans.append(DiffSpan(op="equal", text=text))
        elif op == diff_match_patch.DIFF_DELETE:  # type: ignore[no-untyped-call]
            remove_spans.append(DiffSpan(op="delete", text=text))
        elif op == diff_match_patch.DIFF_INSERT:  # type: ignore[no-untyped-call]
            add_spans.append(DiffSpan(op="insert", text=text))

    return _ensure_spans(remove_spans), _ensure_spans(add_spans)

def _should_char_diff(old_line: str, new_line: str) -> bool:
    return len(old_line) <= DIFF_MAX_LINE_LENGTH_FOR_CHAR_DIFF and len(new_line) <= DIFF_MAX_LINE_LENGTH_FOR_CHAR_DIFF
