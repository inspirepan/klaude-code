from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.protocol.models import DiffUIExtra
from klaude_code.tool.file.diff_builder import build_structured_diff


def _find_spans(diff: DiffUIExtra, kind: str, op: str) -> list[str]:
    spans: list[str] = []
    for line in diff.files[0].lines:
        if line.kind != kind:
            continue
        for span in line.spans:
            if span.op == op:
                spans.append(span.text)
    return spans


def test_char_level_spans_for_replacement():
    before = "hello world\n"
    after = "hello there\n"

    diff = build_structured_diff(before, after, file_path="greeting.txt")

    deleted = _find_spans(diff, "remove", "delete")
    inserted = _find_spans(diff, "add", "insert")

    assert "world" in deleted
    assert "there" in inserted
    assert diff.raw_unified_diff is not None
    assert diff.raw_unified_diff.startswith("--- greeting.txt\n+++ greeting.txt")
    assert "@@" in diff.raw_unified_diff


def test_replace_blocks_are_grouped_remove_then_add() -> None:
    before = "a\nb\nc\n"
    after = "x\ny\nz\n"

    diff = build_structured_diff(before, after, file_path="test.txt")
    kinds = [line.kind for line in diff.files[0].lines]

    assert kinds == ["remove", "remove", "remove", "add", "add", "add"]
    assert [line.old_line_no for line in diff.files[0].lines if line.kind == "remove"] == [1, 2, 3]
    assert [line.new_line_no for line in diff.files[0].lines if line.kind == "add"] == [1, 2, 3]


def test_delete_lines_have_old_line_numbers() -> None:
    before = "keep\ndelete\nalso delete\nkeep too\n"
    after = "keep\nkeep too\n"

    diff = build_structured_diff(before, after, file_path="test.txt")
    remove_lines = [line for line in diff.files[0].lines if line.kind == "remove"]

    assert [line.old_line_no for line in remove_lines] == [2, 3]
    assert [line.new_line_no for line in remove_lines] == [None, None]


def test_eof_newline_only_change_is_visible() -> None:
    before = "hello"
    after = "hello\n"

    diff = build_structured_diff(before, after, file_path="test.txt")

    file_diff = diff.files[0]
    assert [line.kind for line in file_diff.lines] == ["remove", "add"]
    assert file_diff.stats_add == 1
    assert file_diff.stats_remove == 1
    assert diff.raw_unified_diff is not None
    assert "\\ No newline at end of file" in diff.raw_unified_diff


# ============================================================================
# Property-based tests for diff_builder
# ============================================================================


@given(
    before=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=500),
    after=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=500),
)
@settings(max_examples=100, deadline=None)
def test_diff_builder_stats_match_lines(before: str, after: str) -> None:
    """Property: stats_add/stats_remove match actual add/remove line counts."""
    diff = build_structured_diff(before, after, file_path="test.txt")

    actual_add = sum(1 for line in diff.files[0].lines if line.kind == "add")
    actual_remove = sum(1 for line in diff.files[0].lines if line.kind == "remove")

    assert diff.files[0].stats_add == actual_add
    assert diff.files[0].stats_remove == actual_remove


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=500),
)
@settings(max_examples=50, deadline=None)
def test_diff_builder_identical_no_changes(text: str) -> None:
    """Property: identical before/after produces no add/remove lines."""
    diff = build_structured_diff(text, text, file_path="test.txt")

    assert diff.files[0].stats_add == 0
    assert diff.files[0].stats_remove == 0
