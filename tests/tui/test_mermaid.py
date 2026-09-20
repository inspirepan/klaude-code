"""Tests for the Mermaid box-art renderer, ported from grok-build's mermaid.rs test module."""

from __future__ import annotations

from rich.cells import cell_len
from rich.style import Style

from klaude_code.tui.components.rich.mermaid import (
    CONT,
    LABEL_BREAK_CHARS,
    MAX_LINES,
    WRAP_WIDTH,
    ClassInfo,
    Dir,
    Graph,
    Head,
    LineKind,
    MermaidStyles,
    SeqDivider,
    SeqMessage,
    SeqNote,
    Shape,
    compute_ranks,
    count_crossings,
    decode_html_entities,
    order_ranks,
    parse_class,
    parse_er,
    parse_er_op,
    parse_graph,
    parse_sequence,
    parse_state,
    push_er_attribute,
    push_member,
    render,
    wrap_label,
)

_NULL = Style()
STYLES = MermaidStyles(border=_NULL, node_text=_NULL, edge=_NULL, edge_label=_NULL, title=_NULL)


def plain(src: str, width: int | None = 120) -> str:
    art = render(src, STYLES, width)
    assert art is not None
    return "\n".join(art.plain_lines)


def plain_lines(src: str, width: int | None = 120) -> list[str]:
    art = render(src, STYLES, width)
    assert art is not None
    return art.plain_lines


def graph_of(src: str) -> Graph:
    graph = parse_graph(src)
    assert graph is not None
    return graph


def row_of(out: str, needle: str) -> int:
    lines = out.splitlines()
    return next(i for i, line in enumerate(lines) if needle in line)


# --- flowchart parsing -------------------------------------------------------


def test_parses_nodes_edges_and_direction() -> None:
    g = graph_of("flowchart LR\n  A[Start] --> B[End]")
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.nodes[0].label == "Start"
    assert g.nodes[1].label == "End"
    assert g.direction is Dir.RIGHT


def test_non_flowchart_returns_none_from_parse() -> None:
    assert parse_graph("sequenceDiagram\n  A->>B: hi") is None


def test_html_tags_are_stripped_from_labels() -> None:
    g = graph_of('flowchart TD\n  A["<b>Bold</b> and <i>italic</i>"] --> B')
    assert g.nodes[0].label == "Bold and italic"


def test_br_tag_becomes_a_space() -> None:
    g = graph_of('flowchart TD\n  A["Line1<br/>Line2<br>Line3"]')
    assert g.nodes[0].label == "Line1 Line2 Line3"


def test_markdown_string_strips_bold_italic_and_code() -> None:
    g = graph_of('flowchart TD\n  A["`**Start** here`"] --> B["`Save to **database**`"]\n  B --> C["`**Done!**`"]')
    assert g.nodes[0].label == "Start here"
    assert g.nodes[1].label == "Save to database"
    assert g.nodes[2].label == "Done!"


def test_markdown_string_preserves_snake_case_and_strips_inline_code() -> None:
    g = graph_of('flowchart TD\n  A["`_italic_ uses `vocab_size` with __all__`"]')
    assert g.nodes[0].label == "italic uses vocab_size with all"


def test_markdown_string_edge_label_is_stripped() -> None:
    g = graph_of('flowchart TD\n  A -->|"`**yes**`"| B\n  A -->|"`__no__`"| C')
    assert g.edges[0].label == "yes"
    assert g.edges[1].label == "no"


def test_plain_label_keeps_literal_text_and_underscores() -> None:
    g = graph_of('flowchart TD\n  A["[ 464, 3797 ] seq_len d_model"]')
    assert g.nodes[0].label == "[ 464, 3797 ] seq_len d_model"


def test_code_and_span_tags_are_stripped() -> None:
    g = graph_of('flowchart TD\n  A["<code>vocab_size</code> <span style=\\"color:red\\">x</span>"]')
    assert g.nodes[0].label == "vocab_size x"


def test_bare_angle_brackets_are_kept() -> None:
    g = graph_of('flowchart TD\n  A["a < b and c > d"]')
    assert g.nodes[0].label == "a < b and c > d"


def test_generic_types_are_not_stripped_as_html() -> None:
    g = graph_of('flowchart TD\n  A["Returns Vec<String>"] --> B["Option<i32> for <id>"]')
    assert g.nodes[0].label == "Returns Vec<String>"
    assert g.nodes[1].label == "Option<i32> for <id>"


def test_decode_html_entities_covers_named_numeric_and_double_escape() -> None:
    assert decode_html_entities("&lt;a&gt; &amp; &quot;x&quot; &apos;y&apos;") == "<a> & \"x\" 'y'"
    assert decode_html_entities("it&#39;s &#60;ok&#62;") == "it's <ok>"
    assert decode_html_entities("&#x3c;tag&#X3E; &#x27;q&#x27;") == "<tag> 'q'"
    # `&amp;lt;` must yield the literal `&lt;`, never `<`.
    assert decode_html_entities("&amp;lt;") == "&lt;"
    assert decode_html_entities("a &foo; b & c") == "a &foo; b & c"
    # Control chars (NUL collides with CONT, ESC injects ANSI) never decode.
    assert decode_html_entities("a&#27;b&#0;c") == "a&#27;b&#0;c"
    assert decode_html_entities("x&#x1b;y") == "x&#x1b;y"


def test_entity_escaped_flowchart_label_decodes_in_box_art() -> None:
    src = (
        'flowchart LR\n  YAML["models-config/&lt;model&gt;/&lt;env&gt;.yaml\\nenterprise_api_config:"]\n'
        '  PY["model_config_map.py\\nlanguage_model_dict_to_proto()"]\n  YAML --> PY'
    )
    g = graph_of(src)
    assert "models-config/<model>/<env>.yaml" in g.nodes[0].label
    art = plain(src)
    assert "<model>" in art and "<env>" in art
    assert "&lt;" not in art and "&gt;" not in art


def test_direct_push_sinks_decode_entities() -> None:
    g = parse_state(
        'stateDiagram-v2\n  state "work &lt;job&gt;" as J\n  Idle --> Run: "on &lt;go&gt;"\n  Run: "d &lt;e&gt;"'
    )
    assert g is not None
    node_labels = [n.label for n in g.nodes]
    edge_labels = [e.label or "" for e in g.edges]
    assert any("work <job>" in s for s in node_labels)
    assert any("d <e>" in s for s in node_labels)
    assert any("on <go>" in s for s in edge_labels)
    assert not any("&lt;" in s for s in node_labels + edge_labels)

    parsed = parse_class('classDiagram\n  A --> B : "uses &lt;X&gt;"')
    assert parsed is not None
    assert any(e.label and "uses <X>" in e.label and "&lt;" not in e.label for e in parsed[0].edges)

    seq = parse_sequence(
        'sequenceDiagram\n  A->>B: "call &lt;svc&gt;"\n  Note over A,B: "memo &lt;o&gt;"\n  alt "c &lt;x&gt;"\n    A->>B: ok\n  end'
    )
    assert seq is not None
    assert any(isinstance(it, SeqMessage) and it.text and "call <svc>" in it.text for it in seq.items)
    assert any(isinstance(it, SeqNote) and "memo <o>" in it.text for it in seq.items)
    assert any(isinstance(it, SeqDivider) and "c <x>" in it.text for it in seq.items)
    assert not any(isinstance(it, SeqMessage) and it.text and "&lt;" in it.text for it in seq.items)

    member = ClassInfo()
    push_member(member, "+run &lt;R&gt;")
    assert member.attrs == ["+run <R>"]
    attr = ClassInfo()
    push_er_attribute(attr, "string &lt;pk&gt;")
    assert attr.attrs == ["string <pk>"]


def test_quoted_label_with_inner_brackets_is_one_node() -> None:
    g = graph_of('flowchart TD\n  IDs["<b>Token IDs</b><br/>[ 464, 3797 ]<br/><i>indices</i>"]')
    assert len(g.nodes) == 1
    assert len(g.edges) == 0
    assert g.nodes[0].label == "Token IDs [ 464, 3797 ] indices"


def test_unquoted_label_with_embedded_quote_closes_at_bracket() -> None:
    g = graph_of('flowchart TD\n  A[5" pipe] --> B[24" display]')
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.nodes[0].label == '5" pipe'
    assert g.nodes[1].label == '24" display'


def test_quoted_label_with_inner_parens_is_one_node() -> None:
    g = graph_of('flowchart TD\n  A["Tokenizer (BPE / WordPiece)"] --> B[Done]')
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.nodes[0].label == "Tokenizer (BPE / WordPiece)"


def test_diagram_with_html_labels_renders_without_tag_artifacts() -> None:
    out = plain(
        'flowchart TD\n  IDs["<b>3. Token IDs</b><br/>[ 464, 3797 ]<br/><i>indices</i>"] --> Out["<b>done</b>"]'
    )
    assert "<b>" not in out
    assert "</" not in out
    assert "br/" not in out
    assert "Token IDs" in out


def test_ranks_ignore_back_edges() -> None:
    g = graph_of("graph TD\n A-->B\n B-->C\n C-->A")
    r = compute_ranks(g)
    assert r[g.index["A"]] == 0
    assert r[g.index["B"]] == 1
    assert r[g.index["C"]] == 2


def test_td_render_has_boxes_labels_and_arrow() -> None:
    out = plain("graph TD\n A[Start] --> B[End]")
    assert "Start" in out
    assert "End" in out
    assert "┌" in out or "╭" in out
    assert "▼" in out


def test_edge_label_is_rendered() -> None:
    assert "yes" in plain("graph TD\n A-->|yes| B")


def test_lr_is_shorter_than_td_for_a_chain() -> None:
    chain = "A --> B --> C --> D"
    td = len(plain_lines(f"graph TD\n {chain}"))
    lr = len(plain_lines(f"flowchart LR\n {chain}"))
    assert lr < td


def test_unsupported_diagram_uses_fallback_box() -> None:
    out = plain("gantt\n title Plan\n section A\n task :a1, 2024-01-01, 30d")
    assert "mermaid: gantt" in out
    assert "Plan" in out


def test_blank_source_returns_none() -> None:
    assert render("   \n  ", STYLES, 80) is None


def test_inline_label_with_x_or_o_letters() -> None:
    g = graph_of("graph TD\n A -- no exit --> B")
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.edges[0].label == "no exit"


def test_wide_glyph_box_stays_aligned() -> None:
    lines = plain_lines("graph TD\n A[日本語ab]")
    widths = [cell_len(line) for line in lines if line.strip()]
    assert len(set(widths)) == 1, widths
    assert not any(CONT in line for line in lines)


def test_merge_has_single_arrowhead() -> None:
    out = plain("graph TD\n A[aaa] --> D[ddddddd]\n B[bb] --> D\n C[ccccc] --> D")
    assert out.count("▼") == 1
    assert "▼▼" not in out


def test_long_label_wraps_without_truncation() -> None:
    out = plain("graph TD\n A[Check if the user has permission to access resource] --> B[Done]")
    assert "permission" in out
    assert "resource" in out
    assert "…" not in out


def test_very_long_label_truncates_after_max_lines() -> None:
    long = ("alpha " * 40).strip()
    assert "…" in plain(f"graph TD\n A[{long}] --> B[x]")


def test_wrap_label_breaks_long_identifier_on_boundary() -> None:
    lines = wrap_label("mark_filter_restore_context", WRAP_WIDTH, MAX_LINES)
    assert lines[0].endswith("_")
    for line in lines[:-1]:
        assert line[-1] in LABEL_BREAK_CHARS
    assert "".join(lines) == "mark_filter_restore_context"


def test_wrap_label_token_without_break_char_falls_back_per_char() -> None:
    token = "a" * 40
    lines = wrap_label(token, WRAP_WIDTH, MAX_LINES)
    assert len(lines) >= 2
    assert "".join(lines) == token


def test_flowchart_long_identifier_breaks_on_boundary_not_mid_segment() -> None:
    out = plain("graph TD\n A[mark_filter_restore_context] --> B[Done]")
    assert "mark_filter_restore_" in out
    assert "context" in out


def test_wrap_label_mixed_boundary_then_no_boundary_tail() -> None:
    token = "ab_" + "c" * 40
    lines = wrap_label(token, WRAP_WIDTH, MAX_LINES)
    assert lines[0].endswith("_")
    assert any(not any(ch in LABEL_BREAK_CHARS for ch in line) for line in lines[1:])
    assert "".join(lines) == token


def test_wrap_label_boundary_breaking_still_truncates_at_max_lines() -> None:
    ident = "_".join(["segment"] * 20)
    lines = wrap_label(ident, WRAP_WIDTH, MAX_LINES)
    assert len(lines) == MAX_LINES
    assert lines[-1].endswith("…")


def test_bt_flips_orientation() -> None:
    out = plain("flowchart BT\n A[first] --> B[second] --> C[third]")
    assert row_of(out, "third") < row_of(out, "first")


def test_rl_flips_orientation() -> None:
    out = plain("flowchart RL\n A[first] --> B[second] --> C[third]")
    line = next(line for line in out.splitlines() if "first" in line)
    assert line.find("third") < line.find("first")


def test_undirected_piped_label_has_no_arrowhead() -> None:
    out = plain("graph TD\n A ---|maybe| B")
    assert "maybe" in out
    assert "▼" not in out


def test_chain_edges_are_straight() -> None:
    out = plain("graph TD\n A[aaaa] --> B[b] --> C[cccccccc]")
    for line in out.splitlines():
        assert not ("└" in line and "┐" in line), line


def test_adversarial_chain_falls_back() -> None:
    src = "graph TD\n" + "".join(f" N{i} --> N{i + 1}\n" for i in range(10_000))
    assert "mermaid: graph" in plain(src)


def test_single_statement_chain_over_cap_falls_back() -> None:
    src = "graph LR\n " + "".join(f"N{i}-->" for i in range(10_000)) + "N10000"
    assert "mermaid: graph" in plain(src)


def test_deep_chain_within_caps_renders() -> None:
    src = "graph TD\n" + "".join(f" N{i} --> N{i + 1}\n" for i in range(100))
    joined = plain(src, 200)
    assert "N0" in joined
    assert "N100" in joined
    assert "▼" in joined


def test_fallback_styled_and_plain_widths_match() -> None:
    art = render("gantt\n title Plan\n a\n", STYLES, 120)
    assert art is not None
    assert len(art.styled_lines) == len(art.plain_lines)
    frame_w = cell_len(art.plain_lines[0])
    for styled, plain_row in zip(art.styled_lines, art.plain_lines, strict=True):
        assert cell_len(styled.plain) == cell_len(plain_row)
        assert cell_len(plain_row) == frame_w


def test_over_wide_diagram_falls_back() -> None:
    src = "flowchart LR\n A[aaaaaaaaaaaaaaaaaaaa] --> B[bbbbbbbbbbbbbbbbbbbb] --> C[cccccccccccccccccccc]"
    out = plain_lines(src, 40)
    joined = "\n".join(out)
    assert "mermaid: flowchart" in joined
    max_w = max(cell_len(line) for line in out)
    fits = plain_lines(src, 120)
    assert any("▶" in line for line in fits)
    assert max_w <= len(src)


def test_too_wide_fallback_appends_hint_below_box() -> None:
    src = "flowchart LR\n A[aaaaaaaaaaaaaaaaaaaa] --> B[bbbbbbbbbbbbbbbbbbbb] --> C[cccccccccccccccccccc]"
    out = plain_lines(src, 40)
    joined = "\n".join(out)
    assert "mermaid: flowchart" in joined
    assert "(too wide)" not in joined
    assert "flowchart LR" in joined
    bottom = next(i for i, line in enumerate(out) if "╰" in line)
    note = next(i for i, line in enumerate(out) if "too wide" in line)
    assert note > bottom
    assert "source is shown instead" in joined
    assert all(cell_len(line) <= 40 for line in out)


def test_unsupported_diagram_fallback_not_flagged_too_wide() -> None:
    out = plain("gantt\n title Plan\n section A\n task :a1, 2024-01-01, 30d")
    assert "mermaid: gantt" in out
    assert "too wide" not in out


def test_fitting_diagram_has_no_width_warning() -> None:
    out = plain("flowchart LR\n A[Start] --> B[End]")
    assert "too wide" not in out
    assert "mermaid: flowchart" not in out
    assert "▶" in out


def test_bidirectional_link_draws_both_arrowheads() -> None:
    lr = plain("flowchart LR\n A <--> B")
    assert "◄" in lr and "▶" in lr
    td = plain("graph TD\n A <--> B")
    assert "▲" in td and "▼" in td


def test_reversed_arrow_swaps_edge_direction() -> None:
    g = graph_of("graph TD\n A <-- B")
    assert len(g.edges) == 1
    assert g.edges[0].src == g.index["B"]
    assert g.edges[0].dst == g.index["A"]
    assert g.edges[0].head_to is Head.ARROW
    assert g.edges[0].head_from is Head.NONE
    out = plain("graph TD\n A <-- B")
    assert row_of(out, "B") < row_of(out, "A")


def test_semicolon_and_comment_survive_inside_quoted_label() -> None:
    g = graph_of('graph TD\n A["wait; 50%% done"] --> B')
    assert len(g.nodes) == 2
    assert g.nodes[0].label == "wait; 50%% done"


def test_comment_outside_quotes_is_stripped() -> None:
    g = graph_of("graph TD %% main flow\n A --> B %% trailing\n %% full line\n")
    assert len(g.nodes) == 2
    assert len(g.edges) == 1


def test_skip_edge_routes_around_intermediate_boxes() -> None:
    out = plain("graph TD\n A --> B\n B --> C\n A --> C")
    assert "┼" not in out
    assert "◄" in out


def _ordered_ranks(src: str) -> tuple[Graph, list[int], list[list[int]], list[int]]:
    g = graph_of(src)
    ranks = compute_ranks(g)
    by_rank: list[list[int]] = [[] for _ in range(max(ranks) + 1)]
    for idx, r in enumerate(ranks):
        by_rank[r].append(idx)
    order_ranks(by_rank, g.edges, ranks)
    pos = [0] * len(g.nodes)
    for row in by_rank:
        for i, v in enumerate(row):
            pos[v] = i
    return g, ranks, by_rank, pos


def test_order_ranks_removes_avoidable_crossing() -> None:
    g, ranks, _, pos = _ordered_ranks("graph TD\n C[ccc]\n D[ddd]\n A --> D\n B --> C")
    assert count_crossings(g.edges, ranks, pos) == 0
    assert pos[g.index["D"]] < pos[g.index["C"]]


def test_order_ranks_keeps_crossing_free_order() -> None:
    g, ranks, by_rank, pos = _ordered_ranks("graph TD\n A --> C\n B --> D")
    assert by_rank[0] == [g.index["A"], g.index["B"]]
    assert by_rank[1] == [g.index["C"], g.index["D"]]
    assert count_crossings(g.edges, ranks, pos) == 0


def test_crossing_edges_render_untangled() -> None:
    out = plain("graph TD\n C[ccc]\n D[ddd]\n A --> D\n B --> C")
    row = next(line for line in out.splitlines() if "ccc" in line and "ddd" in line)
    assert row.find("ddd") < row.find("ccc")
    assert "┼" not in out


def test_three_layer_weave_untangles() -> None:
    g, ranks, _, pos = _ordered_ranks("graph TD\n X[x]\n Y[y]\n A --> Y\n B --> X\n X --> Q\n Y --> P\n P[p]\n Q[q]")
    assert count_crossings(g.edges, ranks, pos) == 0


def test_unavoidable_crossing_gets_separate_bus_rows() -> None:
    crossing = plain("graph TD\n A --> D[ddd]\n A --> C[ccc]\n B --> C\n B --> D")
    parallel = plain("graph TD\n A --> C[ccc]\n B --> D[ddd]")
    assert "┼" in crossing
    assert len(crossing.splitlines()) == len(parallel.splitlines()) + 1
    assert crossing.count("▼") == 2


def test_fan_out_keeps_single_bus_row() -> None:
    out = plain("graph TD\n A --> C[ccc]\n A --> D[ddd]")
    baseline = plain("graph TD\n A --> C[ccc]")
    assert len(out.splitlines()) == len(baseline.splitlines())
    assert "┼" not in out


def _max_width(out: str) -> int:
    return max(cell_len(line) for line in out.splitlines())


def test_shared_target_back_edges_share_one_lane() -> None:
    two = plain("graph TD\n A --> B\n B --> C\n B --> A\n C --> A")
    one = plain("graph TD\n A --> B\n B --> C\n C --> A")
    assert _max_width(two) == _max_width(one)
    assert two.count("◄") == 1


def test_distinct_back_edges_get_separate_lanes() -> None:
    split = plain("graph TD\n A --> B\n B --> C\n B --> A\n C --> B")
    single = plain("graph TD\n A --> B\n B --> C\n C --> B")
    assert split.count("◄") == 2
    assert _max_width(split) > _max_width(single)


def test_fallback_wraps_long_lines_to_max_width() -> None:
    out = plain_lines("gantt\n title a very long line that should wrap inside the fallback box nicely", 40)
    assert all(cell_len(line) <= 40 for line in out)
    for line in out[1:-1]:
        assert line.startswith("│") and line.endswith("│"), line
    assert "nicely" in "\n".join(out)


# --- class diagrams -----------------------------------------------------------


def test_class_renders_compartments() -> None:
    out = plain("classDiagram\n class Animal {\n +int age\n +isMammal() bool\n }\n Animal <|-- Duck")
    assert "Animal" in out
    assert "+int age" in out
    assert "+isMammal() bool" in out
    assert "├" in out and "┤" in out
    assert row_of(out, "Animal") < row_of(out, "+int age") < row_of(out, "+isMammal() bool")


def test_class_inheritance_triangle_at_parent() -> None:
    out = plain("classDiagram\n Animal <|-- Duck\n Animal <|-- Fish")
    assert "△" in out
    animal = row_of(out, "Animal")
    duck = row_of(out, "Duck")
    assert animal < duck
    tri = row_of(out, "△")
    assert animal <= tri < duck


def test_class_realization_is_dotted_triangle() -> None:
    parsed = parse_class("classDiagram\n IShape <|.. Circle")
    assert parsed is not None
    assert parsed[0].edges[0].head_from is Head.TRIANGLE
    assert parsed[0].edges[0].line is LineKind.DOTTED
    out = plain("classDiagram\n IShape <|.. Circle")
    assert "╎" in out or "╌" in out


def test_class_composition_and_aggregation_diamonds() -> None:
    out = plain("classDiagram\n Car *-- Engine\n Pond o-- Duck")
    assert "◆" in out
    assert "◇" in out


def test_class_dependency_dotted_arrow() -> None:
    parsed = parse_class("classDiagram\n A ..> B")
    assert parsed is not None
    assert parsed[0].edges[0].head_to is Head.ARROW
    assert parsed[0].edges[0].line is LineKind.DOTTED


def test_class_colon_members_merge_with_block() -> None:
    out = plain("classDiagram\n class Duck {\n +swim()\n }\n Duck : +String beakColor\n S --> Duck")
    assert "+swim()" in out
    assert "+String beakColor" in out


def test_class_annotation_renders_guillemets() -> None:
    assert "«interface»" in plain("classDiagram\n <<interface>> Shape\n Shape <|.. Circle")


def test_class_generics_display_as_angle_brackets() -> None:
    out = plain("classDiagram\n Shape~T~ : +area() T\n S --> Shape~T~")
    assert "Shape<T>" in out
    assert "~" not in out


def test_class_cardinalities_fold_into_label() -> None:
    assert "many attends 1" in plain('classDiagram\n Student "many" --> "1" School : attends')


def test_class_from_end_head_survives_fan_out_jog() -> None:
    out = plain("classDiagram\n Animal <|-- Duck\n Animal <|-- Fish\n Animal <|-- Cow")
    assert out.count("△") + out.count("▽") == 1


def test_class_empty_class_is_plain_titled_box() -> None:
    assert "Loner" in plain("classDiagram\n class Loner\n A --> Loner")


def test_class_unknown_statement_falls_back() -> None:
    assert "mermaid: classDiagram" in plain("classDiagram\n A --> B\n total garbage here")


def test_class_member_cap_ellipsis() -> None:
    src = "classDiagram\n class Big {\n" + "".join(f" +field{i}\n" for i in range(12)) + " }\n A --> Big"
    out = plain(src)
    assert "+field7" in out
    assert "+field9" not in out
    assert "…" in out


def test_class_direction_lr() -> None:
    out = plain("classDiagram\n direction LR\n A --> B")
    line = next(line for line in out.splitlines() if "A" in line)
    assert "B" in line


# --- ER diagrams --------------------------------------------------------------


def test_er_renders_entities_and_relationship_labels() -> None:
    out = plain(
        'erDiagram\n CUSTOMER ||--o{ ORDER : places\n CUSTOMER {\n string name PK "full name"\n int custNumber\n }'
    )
    assert "CUSTOMER" in out
    assert "ORDER" in out
    assert "string name PK" in out
    assert "full name" not in out
    assert "1 places 0..*" in out
    assert "├" in out


def test_er_cardinality_map() -> None:
    cases = [
        ("||--||", "1", "1"),
        ("|o--o|", "0..1", "0..1"),
        ("}o--o{", "0..*", "0..*"),
        ("}|--|{", "1..*", "1..*"),
        ("||--o{", "1", "0..*"),
    ]
    for op, left, right in cases:
        parsed = parse_er_op(op)
        assert parsed is not None, op
        assert (parsed[0], parsed[1]) == (left, right), op
        assert parsed[2] is LineKind.SOLID
    dotted = parse_er_op("||..o{")
    assert dotted is not None and dotted[2] is LineKind.DOTTED
    assert parse_er_op("||==o{") is None
    assert parse_er_op("garbage") is None


def test_er_non_identifying_renders_dotted() -> None:
    out = plain("erDiagram\n A ||..o{ B : uses")
    assert "╎" in out or "╌" in out


def test_er_relationships_have_no_arrowheads() -> None:
    out = plain("erDiagram\n A ||--o{ B : has")
    for head in "▼▲◄▶△◆◇":
        assert head not in out


def test_er_entity_alias_label() -> None:
    out = plain('erDiagram\n p[Person] ||--o{ a["Bank Account"] : owns')
    assert "Person" in out
    assert "Bank Account" in out


def test_er_unquoted_label_and_bare_entity_decl() -> None:
    parsed = parse_er("erDiagram\n LONER\n A ||--|| B : linked")
    assert parsed is not None
    assert len(parsed[0].nodes) == 3
    out = plain("erDiagram\n LONER\n A ||--|| B : linked")
    assert "LONER" in out
    assert "1 linked 1" in out


def test_er_attribute_cap_ellipsis() -> None:
    src = "erDiagram\n BIG {\n" + "".join(f" int f{i}\n" for i in range(12)) + " }\n BIG ||--|| OTHER : x"
    out = plain(src)
    assert "int f7" in out
    assert "int f9" not in out
    assert "…" in out


def test_er_unknown_statement_falls_back() -> None:
    assert "mermaid: erDiagram" in plain("erDiagram\n A ||--|| B : ok\n utter nonsense statement")


# --- subgraphs ----------------------------------------------------------------


def test_subgraph_renders_titled_frame() -> None:
    out = plain("graph TD\n S[Start] --> one\n subgraph one [Group One]\n A --> B\n end\n one --> E[End]")
    assert " Group One " in out
    lines = out.splitlines()
    title = row_of(out, "Group One")
    a = row_of(out, "│ A │")
    b = row_of(out, "│ B │")
    frame_close = max(i for i, line in enumerate(lines) if line.lstrip().startswith("└"))
    assert title < a < b <= frame_close
    assert "Start" in out and "End" in out
    assert out.count("▼") == 3


def test_subgraph_edge_between_groups() -> None:
    out = plain("graph TD\n subgraph api [API]\n A1 --> A2\n end\n subgraph db [Storage]\n B1\n end\n api --> db")
    assert " API " in out
    assert " Storage " in out
    assert row_of(out, "API") < row_of(out, "Storage")


def test_subgraph_nested_frames() -> None:
    out = plain(
        "graph TD\n subgraph outer [Outer]\n subgraph inner [Inner]\n X --> Y\n end\n W --> X\n end\n S --> outer"
    )
    assert " Outer " in out
    assert " Inner " in out
    assert row_of(out, "Outer") < row_of(out, "Inner")


def test_subgraph_cross_member_edge_attaches_to_frame() -> None:
    out = plain("graph LR\n S --> A\n subgraph g [Workers]\n A --> B\n end\n B --> T")
    assert " Workers " in out
    assert "S" in out and "T" in out
    assert out.count("▶") == 3
    row = next(line for line in out.splitlines() if "│ A ├" in line)
    assert row.find("S") < row.find("A")


def test_subgraph_id_referenced_before_declaration() -> None:
    g = graph_of("graph TD\n X --> two\n subgraph two\n C --> D\n end")
    assert len(g.groups) == 1
    out = plain("graph TD\n X --> two\n subgraph two\n C --> D\n end")
    assert " two " in out
    assert "│ C │" in out


def test_subgraph_quoted_and_plain_titles() -> None:
    assert " My Stuff " in plain('graph TD\n subgraph "My Stuff"\n A\n end\n S --> A')
    assert " batch jobs " in plain("graph TD\n subgraph batch jobs\n B\n end\n S --> B")
    out3 = plain('graph TD\n subgraph "a &lt;b&gt;"\n C\n end\n S --> C')
    assert "a <b>" in out3 and "&lt;" not in out3


def test_subgraph_empty_is_dropped() -> None:
    out = plain("graph TD\n subgraph ghost\n end\n A --> B")
    assert "ghost" not in out
    assert "▼" in out


def test_subgraph_bt_flips_frame_and_contents() -> None:
    out = plain("flowchart BT\n S --> one\n subgraph one [Up]\n A --> B\n end")
    assert " Up " in out
    assert row_of(out, "│ B │") < row_of(out, "│ A │")
    assert row_of(out, " Up ") < row_of(out, "S")
    assert "▲" in out


def test_subgraph_depth_over_cap_falls_back() -> None:
    src = "graph TD\n" + "".join(f" subgraph g{i}\n" for i in range(8)) + " A --> B\n" + " end\n" * 8
    assert "mermaid: graph" in plain(src)


def test_subgraph_groupless_path_unchanged() -> None:
    assert graph_of("graph TD\n A --> B").groups == []


# --- link syntax --------------------------------------------------------------


def test_fan_out_creates_cross_product_edges() -> None:
    g = graph_of("graph TD\n A & B --> C & D")
    assert len(g.nodes) == 4
    assert len(g.edges) == 4

    def has(f: str, t: str) -> bool:
        return any(e.src == g.index[f] and e.dst == g.index[t] for e in g.edges)

    assert has("A", "C") and has("A", "D") and has("B", "C") and has("B", "D")
    assert plain("graph TD\n A & B --> C & D").count("▼") == 2


def test_fan_out_in_chain() -> None:
    assert len(graph_of("graph LR\n A & B --> C --> D").edges) == 3


def test_fan_out_with_reversed_arrow() -> None:
    g = graph_of("graph TD\n A & B <-- C")
    assert len(g.edges) == 2
    assert all(e.src == g.index["C"] for e in g.edges)
    assert all(e.head_to is Head.ARROW for e in g.edges)


def test_circle_and_cross_endings_create_no_phantom_nodes() -> None:
    g = graph_of("graph TD\n A --o B\n C --x D")
    assert len(g.nodes) == 4
    assert "o" not in g.index
    assert "x" not in g.index
    assert g.edges[0].head_to is Head.CIRCLE
    assert g.edges[1].head_to is Head.CROSS
    assert "o" in plain("graph TD\n A --o B")


def test_left_endings_decorate_without_reversing() -> None:
    g = graph_of("graph TD\n A o-- B\n C x-- D")
    assert g.edges[0].src == g.index["A"]
    assert g.edges[0].dst == g.index["B"]
    assert g.edges[0].head_from is Head.CIRCLE
    assert g.edges[1].head_from is Head.CROSS
    assert g.edges[0].head_to is Head.NONE


def test_reversed_arrow_with_end_marker_swaps_direction() -> None:
    g = graph_of("graph TD\n A <--o B\n C <--x D")
    assert g.edges[0].src == g.index["B"]
    assert g.edges[0].dst == g.index["A"]
    assert g.edges[0].head_to is Head.ARROW
    assert g.edges[0].head_from is Head.CIRCLE
    assert g.edges[1].src == g.index["D"]
    assert g.edges[1].dst == g.index["C"]
    assert g.edges[1].head_from is Head.CROSS
    out = plain("graph TD\n A <--o B")
    assert row_of(out, "B") < row_of(out, "A")


def test_both_end_markers_parse() -> None:
    g = graph_of("graph TD\n A o--o B\n C x--x D")
    assert g.edges[0].head_from is Head.CIRCLE
    assert g.edges[0].head_to is Head.CIRCLE
    assert g.edges[1].head_from is Head.CROSS
    assert g.edges[1].head_to is Head.CROSS
    assert len(g.nodes) == 4


def test_dotted_and_thick_lines_render_distinctly() -> None:
    assert "╎" in plain("graph TD\n A -.-> B")
    assert "┃" in plain("graph TD\n A ==> B")
    solid = plain("graph TD\n A --> B")
    assert "╎" not in solid and "┃" not in solid


def test_dotted_label_form_renders_dashed() -> None:
    out = plain("graph LR\n A -. maybe .-> B")
    assert "╌" in out
    assert "maybe" in out


def test_thick_jog_uses_thick_corners() -> None:
    out = plain("graph TD\n A[aaaaaaa] ==> B\n A ==> C[ccccccc]")
    assert "┏" in out or "┓" in out or "┳" in out


def test_mixed_solid_and_dotted_bus_stays_light() -> None:
    out = plain("graph TD\n A --> C\n B -.-> C")
    assert "╌" in out
    assert "─" in out
    assert "┬" in out


def test_box_borders_stay_light_next_to_styled_edges() -> None:
    out = plain("graph TD\n A ==> B")
    assert "┌" in out and "└" in out
    assert "┏" not in out


def test_self_loop_renders_below_box() -> None:
    out = plain("graph TD\n A --> A")
    assert "╰" in out and "╯" in out
    assert "▲" in out


def test_self_loop_label_renders() -> None:
    assert "again" in plain("graph TD\n A -->|again| A")


def test_self_loop_coexists_with_forward_edge() -> None:
    out = plain("graph TD\n A --> A\n A --> B")
    assert "▲" in out
    assert "▼" in out
    assert "B" in out
    assert "┼" not in out


def test_self_loop_flips_with_bt() -> None:
    out = plain("flowchart BT\n A --> A\n A --> B")
    assert "▼" in out
    assert "╭" in out or "╮" in out


def test_self_loop_in_lr() -> None:
    out = plain("flowchart LR\n A --> A\n A --> B")
    assert "▲" in out
    assert "▶" in out


def test_inline_o_word_label_still_parses_as_label() -> None:
    g = graph_of("graph TD\n A -- or else --> B")
    assert len(g.nodes) == 2
    assert g.edges[0].label == "or else"


# --- state diagrams -----------------------------------------------------------


def test_state_diagram_renders_states_and_transitions() -> None:
    out = plain("stateDiagram-v2\n [*] --> Idle\n Idle --> Running: start\n Running --> [*]")
    assert "Idle" in out
    assert "Running" in out
    assert "start" in out
    assert "▼" in out
    assert out.count("●") == 2
    lines = out.splitlines()
    first_dot = next(i for i, line in enumerate(lines) if "●" in line)
    last_dot = max(i for i, line in enumerate(lines) if "●" in line)
    assert first_dot < row_of(out, "Idle") < last_dot


def test_state_v1_header_renders() -> None:
    assert "▼" in plain("stateDiagram\n A --> B")


def test_state_boxes_are_rounded() -> None:
    out = plain("stateDiagram-v2\n A --> B")
    assert "╭" in out
    assert "┌" not in out


def test_state_alias_label_renders() -> None:
    assert "Waiting for input" in plain('stateDiagram-v2\n state "Waiting for input" as W\n W --> Done')


def test_state_choice_parses_as_diamond() -> None:
    g = parse_state("stateDiagram-v2\n state c <<choice>>\n A --> c\n c --> B: yes\n c --> D: no")
    assert g is not None
    assert g.nodes[g.index["c"]].shape is Shape.DIAMOND
    assert len(g.edges) == 3


def test_state_description_sets_label() -> None:
    assert "waits patiently" in plain("stateDiagram-v2\n s2 : waits patiently\n A --> s2")


def test_state_direction_lr() -> None:
    out = plain("stateDiagram-v2\n direction LR\n A --> B --> C")
    td = plain("stateDiagram-v2\n A --> B")
    assert len(out.splitlines()) <= len(td.splitlines()) + 2
    line = next(line for line in out.splitlines() if "A" in line)
    assert "B" in line


def test_state_composite_contents_render_flat() -> None:
    out = plain("stateDiagram-v2\n state Active {\n A --> B\n }\n Active --> Done")
    assert "Active" in out
    assert "A" in out and "B" in out
    assert "Done" in out


def test_state_notes_are_skipped() -> None:
    out = plain("stateDiagram-v2\n A --> B\n note right of A: inline note\n note left of B\n block text\n end note")
    assert "▼" in out
    assert "note" not in out
    assert "block text" not in out


def test_state_back_transition_uses_lane() -> None:
    out = plain("stateDiagram-v2\n A --> B\n B --> C\n C --> B: retry")
    assert "◄" in out
    assert "retry" in out


def test_state_unknown_statement_falls_back() -> None:
    assert "mermaid: stateDiagram-v2" in plain("stateDiagram-v2\n A --> B\n some garbage line")


def test_state_over_cap_falls_back() -> None:
    src = "stateDiagram-v2\n" + "".join(f" S{i} --> S{i + 1}\n" for i in range(600))
    assert "mermaid: stateDiagram-v2" in plain(src)


def test_state_extra_dash_arrow_tolerated() -> None:
    g = parse_state("stateDiagram-v2\n A ---> B")
    assert g is not None
    assert len(g.edges) == 1
    assert len(g.nodes) == 2


def test_state_description_preserves_choice_shape() -> None:
    g = parse_state("stateDiagram-v2\n state c <<choice>>\n c : pick a path\n A --> c\n c --> B")
    assert g is not None
    assert g.nodes[g.index["c"]].shape is Shape.DIAMOND
    assert g.nodes[g.index["c"]].label == "pick a path"
    g2 = parse_state('stateDiagram-v2\n state c <<choice>>\n state "pick" as c\n A --> c')
    assert g2 is not None
    assert g2.nodes[g2.index["c"]].shape is Shape.DIAMOND
    assert g2.nodes[g2.index["c"]].label == "pick"


def test_state_chained_transitions_parse_as_separate_edges() -> None:
    g = parse_state("stateDiagram-v2\n A --> B --> C")
    assert g is not None
    assert len(g.nodes) == 3
    assert len(g.edges) == 2
    assert "B" in g.index and "C" in g.index
    assert not any("-->" in n.label for n in g.nodes)
    assert any(e.src == g.index["A"] and e.dst == g.index["B"] for e in g.edges)
    assert any(e.src == g.index["B"] and e.dst == g.index["C"] for e in g.edges)


def test_state_chain_with_markers_and_label() -> None:
    g = parse_state("stateDiagram-v2\n [*] --> A --> B: done")
    assert g is not None
    assert len(g.edges) == 2
    assert any(e.label == "done" for e in g.edges)
    out = plain("stateDiagram-v2\n [*] --> A --> B: done")
    assert "●" in out
    assert "done" in out


def test_state_dangling_chain_falls_back() -> None:
    assert "mermaid: stateDiagram-v2" in plain("stateDiagram-v2\n A --> B -->")


# --- sequence diagrams --------------------------------------------------------


def test_sequence_renders_actors_and_messages() -> None:
    out = plain("sequenceDiagram\n Alice->>Bob: Hello Bob\n Bob-->>Alice: Hi Alice")
    assert "Alice" in out
    assert "Bob" in out
    assert "Hello Bob" in out
    assert "▶" in out
    assert "◄" in out
    assert "╌" in out
    assert out.count("│ Alice │") == 2


def test_sequence_participant_as_label() -> None:
    out = plain("sequenceDiagram\n participant C as Client\n participant S as Server\n C->>S: GET /")
    assert "Client" in out
    assert "Server" in out


def test_sequence_declared_order_wins() -> None:
    out = plain("sequenceDiagram\n participant B\n participant A\n A->>B: hi")
    line = out.splitlines()[1]
    assert line.find("B") < line.find("A")


def test_sequence_self_message_loops() -> None:
    out = plain("sequenceDiagram\n A->>A: think")
    assert "╮" in out
    assert "╯" in out
    assert "think" in out


def test_sequence_cross_head() -> None:
    assert "×" in plain("sequenceDiagram\n A-x B: lost")


def test_sequence_note_over_renders_box() -> None:
    assert "happy path" in plain("sequenceDiagram\n A->>B: hi\n Note over A,B: happy path")


def test_sequence_autonumber_prefixes_messages() -> None:
    out = plain("sequenceDiagram\n autonumber\n A->>B: one\n B->>A: two")
    assert "1. one" in out
    assert "2. two" in out


def test_sequence_loop_renders_divider_and_end() -> None:
    out = plain("sequenceDiagram\n A->>B: hi\n loop retry x3\n A->>B: again\n end")
    assert "loop retry x3" in out
    assert " end " in out


def test_sequence_rect_block_is_invisible() -> None:
    out = plain("sequenceDiagram\n rect rgb(0,0,0)\n A->>B: hi\n end")
    assert "rect" not in out
    assert " end " not in out


def test_sequence_box_end_does_not_close_enclosing_block() -> None:
    out = plain("sequenceDiagram\n loop l1\n box g\n participant A\n end\n A->>B: hi\n A->>B: bye\n end")
    assert out.count(" end ") == 1
    assert row_of(out, "loop l1") < row_of(out, "hi")
    assert row_of(out, "bye") < row_of(out, " end ")
    assert "box" not in out


def test_sequence_critical_option_renders_dividers() -> None:
    out = plain("sequenceDiagram\n critical connect\n A->>B: try\n option timeout\n A->>A: log\n end")
    assert "critical connect" in out
    assert "option timeout" in out
    assert " end " in out


def test_sequence_long_label_widens_gap() -> None:
    out = plain("sequenceDiagram\n A->>B: a very long message label that needs room\n B-->>A: ok")
    assert "a very long message label that needs room" in out


def test_sequence_unparseable_arrow_falls_back() -> None:
    assert "mermaid: sequenceDiagram" in plain("sequenceDiagram\n ->>B: orphan")


def test_sequence_unknown_statement_falls_back() -> None:
    assert "mermaid: sequenceDiagram" in plain("sequenceDiagram\n A->>B: hi\n garbage statement here")


def test_sequence_over_wide_falls_back() -> None:
    out = plain("sequenceDiagram\n A->>B: this label is far wider than the available pane width", 30)
    assert "mermaid: sequenceDiagram" in out


def test_sequence_over_cap_falls_back() -> None:
    src = "sequenceDiagram\n" + "".join(f" A->>B: msg {i}\n" for i in range(600))
    assert "mermaid: sequenceDiagram" in plain(src)


def test_sequence_activation_markers_are_stripped() -> None:
    out = plain("sequenceDiagram\n A->>+B: call\n B-->>-A: return")
    assert "call" in out
    assert "return" in out
    assert "+" not in out


def test_sequence_rows_are_rectangular_and_sentinel_free() -> None:
    out = plain("sequenceDiagram\n Alice->>Bob: hi\n Note over Alice: solo note")
    assert CONT not in out
    assert "solo note" in out
