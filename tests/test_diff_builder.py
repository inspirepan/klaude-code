from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.core.tool.file.diff_builder import build_structured_diff
from klaude_code.protocol import model


def _find_spans(diff: model.DiffUIExtra, kind: str, op: str) -> list[str]:
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


def test_replace_blocks_are_grouped_remove_then_add() -> None:
    before = "a\nb\nc\n"
    after = "x\ny\nz\n"

    diff = build_structured_diff(before, after, file_path="test.txt")
    kinds = [line.kind for line in diff.files[0].lines]

    assert kinds == ["remove", "remove", "remove", "add", "add", "add"]
    assert [line.new_line_no for line in diff.files[0].lines if line.kind == "add"] == [1, 2, 3]


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
