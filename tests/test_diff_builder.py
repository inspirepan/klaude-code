from klaude_code.core.tool.file.diff_builder import build_structured_diff


def _find_spans(diff, kind: str, op: str) -> list[str]:
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
