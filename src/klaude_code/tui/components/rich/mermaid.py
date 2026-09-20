"""Self-contained terminal renderer for Mermaid diagrams.

Ported from grok-build's `crates/codegen/xai-grok-markdown/src/mermaid.rs`
(commit b189869). Renders `graph`/`flowchart`, `stateDiagram`, `classDiagram`,
`erDiagram` and `sequenceDiagram` blocks as Unicode box-drawing art; unsupported
diagram types fall back to the raw source in a framed box.

Coordinates are terminal cells. Every layout routine works on a `Canvas` of
characters plus a per-cell class (border / text / edge / edge label) that maps to
a Rich style when the canvas is turned into lines.
"""

from __future__ import annotations

import itertools
import math
import string
import unicodedata
from dataclasses import dataclass, field
from enum import Enum, IntEnum

from rich.cells import cell_len, get_character_cell_size
from rich.style import Style
from rich.text import Text


@dataclass(frozen=True)
class MermaidStyles:
    """Theme-derived styles used when painting a diagram."""

    border: Style
    node_text: Style
    edge: Style
    edge_label: Style
    title: Style


@dataclass
class MermaidArt:
    """Rendered diagram: styled lines for Rich and plain lines for tests/plain output."""

    styled_lines: list[Text]
    plain_lines: list[str]


MAX_LABEL = 28
PAD = 1
GAP_X = 3
GAP_Y = 2
# Node labels wrap to at most this many display columns per line, and at most
# this many lines (overflow is truncated with an ellipsis).
WRAP_WIDTH = 24
MAX_LINES = 4
# Identifier-boundary characters preferred as break points when a single word
# is too wide to fit, so it is not sliced mid-segment.
LABEL_BREAK_CHARS = "_-./"
# Sentinel marking the trailing column of a wide glyph (never emitted).
CONT = "\x00"
MAX_NODES = 128
MAX_EDGES = 512
MAX_GROUPS = 24
MAX_GROUP_DEPTH = 6
MAX_CANVAS_CELLS = 1 << 21


def _char_width(c: str) -> int:
    return get_character_cell_size(c)


def _char_w1(c: str) -> int:
    """Display width of a glyph, never less than one column."""
    return max(get_character_cell_size(c), 1)


class Oversize(Enum):
    WIDTH = "width"
    CELLS = "cells"


class _OversizeError(Exception):
    def __init__(self, kind: Oversize) -> None:
        super().__init__(kind.value)
        self.kind = kind


class Shape(Enum):
    RECT = "rect"
    ROUND = "round"
    DIAMOND = "diamond"


class Head(Enum):
    NONE = "none"
    ARROW = "arrow"
    CIRCLE = "circle"
    CROSS = "cross"
    TRIANGLE = "triangle"
    DIAMOND_FILL = "diamond_fill"
    DIAMOND_OPEN = "diamond_open"


class LineKind(Enum):
    SOLID = "solid"
    DOTTED = "dotted"
    THICK = "thick"


class Dir(Enum):
    DOWN = "down"
    UP = "up"
    RIGHT = "right"
    LEFT = "left"


_DIR_MAP: dict[str, Dir] = {"LR": Dir.RIGHT, "RL": Dir.LEFT, "BT": Dir.UP}


def _parse_dir(token: str) -> Dir:
    return _DIR_MAP.get(token.upper(), Dir.DOWN)


@dataclass
class Node:
    label: str
    shape: Shape


@dataclass
class Edge:
    src: int
    dst: int
    label: str | None
    head_to: Head
    head_from: Head
    line: LineKind


@dataclass
class Group:
    key: str
    label: str
    parent: int | None


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    index: dict[str, int] = field(default_factory=dict)
    groups: list[Group] = field(default_factory=list)
    node_group: list[int | None] = field(default_factory=list)
    cur_group: int | None = None
    over_cap: bool = False
    direction: Dir = Dir.DOWN

    def node_index(self, node_id: str, label: str | None, shape: Shape) -> int | None:
        existing = self.index.get(node_id)
        if existing is not None:
            if label is not None:
                self.nodes[existing].label = label
                self.nodes[existing].shape = shape
            return existing
        if len(self.nodes) >= MAX_NODES:
            self.over_cap = True
            return None
        self.index[node_id] = len(self.nodes)
        self.nodes.append(Node(label if label is not None else node_id, shape))
        self.node_group.append(self.cur_group)
        return len(self.nodes) - 1

    def node_label(self, node_id: str, label: str) -> int | None:
        existing = self.index.get(node_id)
        if existing is not None:
            self.nodes[existing].label = label
            return existing
        return self.node_index(node_id, label, Shape.ROUND)


def _has_ws(s: str) -> bool:
    return any(c.isspace() for c in s)


def _non_empty(s: str) -> str | None:
    return s if s else None


def _first_word_of(st: str) -> str:
    words = st.split()
    return words[0] if words else ""


def _statements(src: str) -> list[str]:
    out: list[str] = []
    for raw_line in src.splitlines():
        _split_statements(raw_line, out)
    return out


def _split_statements(line: str, out: list[str]) -> None:
    cur: list[str] = []
    in_quotes = False
    n = len(line)
    i = 0
    while i < n:
        c = line[i]
        if in_quotes:
            if c == '"':
                in_quotes = False
            cur.append(c)
        elif c == '"':
            in_quotes = True
            cur.append(c)
        elif c == "%" and i + 1 < n and line[i + 1] == "%":
            break
        elif c == ";":
            _flush_statement(cur, out)
        else:
            cur.append(c)
        i += 1
    _flush_statement(cur, out)


def _flush_statement(cur: list[str], out: list[str]) -> None:
    trimmed = "".join(cur).strip()
    if trimmed:
        out.append(trimmed)
    cur.clear()


# ---------------------------------------------------------------------------
# Flowchart parsing
# ---------------------------------------------------------------------------

_FLOWCHART_SKIP = {"classdef", "class", "style", "linkstyle", "click", "direction"}


def parse_graph(src: str) -> Graph | None:
    statements = _statements(src)
    if not statements:
        return None
    header_tokens = statements[0].split()
    if not header_tokens:
        return None
    kind = header_tokens[0].lower()
    if kind not in ("graph", "flowchart"):
        return None
    direction = _parse_dir(header_tokens[1] if len(header_tokens) > 1 else "TB")

    graph = Graph(direction=direction)
    stack: list[int] = []
    for st in statements[1:]:
        first = _first_word_of(st).lower()
        if first == "subgraph":
            if len(graph.groups) >= MAX_GROUPS or len(stack) >= MAX_GROUP_DEPTH:
                return None
            key, label = _parse_subgraph_decl(st[len("subgraph") :].strip())
            graph.groups.append(Group(key, label, stack[-1] if stack else None))
            stack.append(len(graph.groups) - 1)
            graph.cur_group = stack[-1]
            continue
        if first == "end":
            if stack:
                stack.pop()
            graph.cur_group = stack[-1] if stack else None
            continue
        if first in _FLOWCHART_SKIP:
            continue
        _parse_statement(st, graph)
        if graph.over_cap:
            return None

    if not graph.nodes:
        return None
    return graph


def _parse_subgraph_decl(rest: str) -> tuple[str, str]:
    if rest.startswith('"'):
        quoted = rest[1:]
        if '"' in quoted:
            label = quoted.split('"', 1)[0]
            return label, decode_html_entities(label)
    open_pos = rest.find("[")
    if open_pos != -1:
        key = rest[:open_pos].strip()
        label = clean_label(rest[open_pos + 1 :].rstrip("]").strip())
        if key and label:
            return key, label
    return rest, rest


def _parse_statement(st: str, graph: Graph) -> None:
    group = _parse_node_group(st, 0, graph)
    if group is None:
        return
    prev, i = group

    while True:
        i = _skip_spaces(st, i)
        if i >= len(st):
            break
        link = _parse_link(st, i)
        if link is None:
            break
        left, right, line, label, ni = link
        i = _skip_spaces(st, ni)
        group = _parse_node_group(st, i, graph)
        if group is None:
            break
        nxt, i = group
        for f in prev:
            for t in nxt:
                if len(graph.edges) >= MAX_EDGES:
                    graph.over_cap = True
                    return
                if left == Head.ARROW and right != Head.ARROW:
                    src, dst, head_to, head_from = t, f, Head.ARROW, right
                else:
                    src, dst, head_to, head_from = f, t, right, left
                graph.edges.append(Edge(src, dst, label, head_to, head_from, line))
        prev = nxt


def _parse_node_group(chars: str, start: int, graph: Graph) -> tuple[list[int], int] | None:
    first = _parse_node(chars, start, graph)
    if first is None:
        return None
    idx, i = first
    group = [idx]
    while True:
        j = _skip_spaces(chars, i)
        if j >= len(chars) or chars[j] != "&":
            break
        nxt = _parse_node(chars, j + 1, graph)
        if nxt is None:
            return None
        group.append(nxt[0])
        i = nxt[1]
    return group, i


def _skip_spaces(chars: str, i: int) -> int:
    n = len(chars)
    while i < n and chars[i] in " \t":
        i += 1
    return i


def _is_id_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def _parse_node(chars: str, start: int, graph: Graph) -> tuple[int, int] | None:
    n = len(chars)
    i = _skip_spaces(chars, start)
    id_start = i
    while i < n and _is_id_char(chars[i]):
        i += 1
    if i == id_start:
        return None
    node_id = chars[id_start:i]

    c = chars[i] if i < n else ""
    c2 = chars[i + 1] if i + 1 < n else ""
    shape: Shape | None
    label: str | None
    if c == "[":
        if c2 == "[":
            shape, label, after = _read_shape(chars, i + 2, "]]", Shape.RECT)
        elif c2 == "(":
            shape, label, after = _read_shape(chars, i + 2, ")]", Shape.ROUND)
        else:
            shape, label, after = _read_shape(chars, i + 1, "]", Shape.RECT)
    elif c == "(":
        if c2 == "(":
            shape, label, after = _read_shape(chars, i + 2, "))", Shape.ROUND)
        elif c2 == "[":
            shape, label, after = _read_shape(chars, i + 2, "])", Shape.ROUND)
        else:
            shape, label, after = _read_shape(chars, i + 1, ")", Shape.ROUND)
    elif c == "{":
        if c2 == "{":
            shape, label, after = _read_shape(chars, i + 2, "}}", Shape.DIAMOND)
        else:
            shape, label, after = _read_shape(chars, i + 1, "}", Shape.DIAMOND)
    elif c == ">":
        shape, label, after = _read_shape(chars, i + 1, "]", Shape.RECT)
    else:
        shape, label, after = None, None, i

    idx = graph.node_index(node_id, label, shape if shape is not None else Shape.RECT)
    if idx is None:
        return None
    return idx, after


def _read_shape(chars: str, start: int, closer: str, shape: Shape) -> tuple[Shape, str, int]:
    n = len(chars)
    j = start
    while j < n and chars[j] in " \t":
        j += 1
    quoted = j < n and chars[j] == '"'
    text: list[str] = []
    in_quotes = False
    i = start
    while i < n:
        c = chars[i]
        if quoted and c == '"':
            in_quotes = not in_quotes
            text.append(c)
            i += 1
            continue
        if not in_quotes and chars.startswith(closer, i):
            return shape, clean_label("".join(text)), i + len(closer)
        text.append(c)
        i += 1
    return shape, clean_label("".join(text)), n


def clean_label(raw: str) -> str:
    stripped = _strip_html_tags(raw.strip())
    trimmed = stripped.strip()
    unquoted = trimmed
    if len(trimmed) >= 2 and trimmed[0] == trimmed[-1] and trimmed[0] in "\"'":
        unquoted = trimmed[1:-1]
    unquoted = unquoted.strip()
    if len(unquoted) >= 2 and unquoted[0] == "`" and unquoted[-1] == "`":
        text = _strip_markdown(unquoted[1:-1].strip())
    else:
        text = unquoted
    # Decode after tag-stripping so `<b>` is removed as markup while `&lt;b&gt;`
    # survives as a literal `<b>`; one decode at the single return covers both paths.
    return decode_html_entities(text)


ENTITY_LOOKAHEAD = 10

_NAMED_ENTITIES: dict[str, str] = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}


def decode_html_entities(s: str) -> str:
    """Decode named/numeric HTML entities once; stray `&` and control chars stay literal."""
    if "&" not in s:
        return s
    out: list[str] = []
    n = len(s)
    i = 0
    while i < n:
        if s[i] != "&":
            out.append(s[i])
            i += 1
            continue
        # Scan window (includes the terminating `;`) so a stray `&` or over-long run stays literal.
        hi = min(i + 1 + ENTITY_LOOKAHEAD, n)
        semi = -1
        for j in range(i + 1, hi):
            if s[j] == ";":
                semi = j
                break
        decoded = _decode_entity_body(s[i + 1 : semi]) if semi != -1 else None
        if decoded is not None:
            # Resume past the `;`; the single pass never re-scans emitted text, so
            # `&amp;lt;` decodes to the literal `&lt;` rather than to `<`.
            out.append(decoded)
            i = semi + 1
        else:
            out.append("&")
            i += 1
    return "".join(out)


def _decode_entity_body(body: str) -> str | None:
    named = _NAMED_ENTITIES.get(body)
    if named is not None:
        return named
    if not body.startswith("#"):
        return None
    num = body[1:]
    if num[:1] in ("x", "X"):
        digits = num[1:]
        if not digits or any(c not in string.hexdigits for c in digits):
            return None
        code = int(digits, 16)
    else:
        if not num or not (num.isascii() and num.isdigit()):
            return None
        code = int(num, 10)
    if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
        return None
    ch = chr(code)
    # Reject control chars: NUL collides with the CONT sentinel and ESC would inject ANSI into scrollback.
    if unicodedata.category(ch) == "Cc":
        return None
    return ch


def _strip_markdown(s: str) -> str:
    no_code = s.replace("`", "")
    no_strong = no_code.replace("**", "").replace("__", "")
    out: list[str] = []
    n = len(no_strong)
    for i, c in enumerate(no_strong):
        if c in "*_" and not (i > 0 and no_strong[i - 1].isalnum() and i + 1 < n and no_strong[i + 1].isalnum()):
            continue
        out.append(c)
    return "".join(out).strip()


HTML_FORMAT_TAGS = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "s",
        "strike",
        "del",
        "ins",
        "mark",
        "small",
        "big",
        "sub",
        "sup",
        "code",
        "kbd",
        "samp",
        "var",
        "tt",
        "span",
        "font",
        "q",
        "abbr",
        "cite",
        "pre",
    }
)


def _strip_html_tags(s: str) -> str:
    out: list[str] = []
    n = len(s)
    i = 0
    while i < n:
        if s[i] == "<":
            tag = _html_tag_at(s, i)
            if tag is not None:
                name, end = tag
                lower = name.lower()
                if lower == "br":
                    out.append(" ")
                    i = end
                    continue
                if lower in HTML_FORMAT_TAGS:
                    i = end
                    continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _html_tag_at(chars: str, start: int) -> tuple[str, int] | None:
    n = len(chars)
    i = start + 1
    if i < n and chars[i] == "/":
        i += 1
    name_start = i
    while i < n and chars[i].isascii() and chars[i].isalnum():
        i += 1
    if i == name_start:
        return None
    name = chars[name_start:i]
    while i < n and chars[i] != ">":
        if chars[i] == "<":
            return None
        i += 1
    if i < n and chars[i] == ">":
        return name, i + 1
    return None


def _is_link_char(c: str) -> bool:
    return c in "-.=<>"


def _parse_link(chars: str, start: int) -> tuple[Head, Head, LineKind, str | None, int] | None:
    n = len(chars)
    i = _skip_spaces(chars, start)
    left = Head.NONE
    if i < n and chars[i] in "ox" and i + 1 < n and chars[i + 1] in "-.=":
        left = Head.CIRCLE if chars[i] == "o" else Head.CROSS
        i += 1
    op_start = i
    while i < n and chars[i] in "-.=<>":
        i += 1
    if i == op_start:
        return None
    op1 = chars[op_start:i]
    if left == Head.NONE and op1.startswith("<"):
        left = Head.ARROW
    line = _line_kind(op1)
    right = Head.ARROW if ">" in op1 else Head.NONE
    if right == Head.NONE:
        trailing = _trailing_head(chars, i)
        if trailing is not None:
            right, i = trailing

    if i < n and chars[i] == "|":
        i += 1
        l_start = i
        while i < n and chars[i] != "|":
            i += 1
        label = clean_label(chars[l_start:i])
        if i < n and chars[i] == "|":
            i += 1
        return left, right, line, _non_empty(label), i

    if right == Head.NONE:
        text_start = _skip_spaces(chars, i)
        j = text_start
        while j < n and not _is_link_char(chars[j]):
            j += 1
        if j < n and j > text_start and chars[j] in "-.=>":
            text = chars[text_start:j]
            op2_start = j
            while j < n and _is_link_char(chars[j]):
                j += 1
            op2 = chars[op2_start:j]
            if ">" in op2:
                right = Head.ARROW
            else:
                trailing = _trailing_head(chars, j)
                if trailing is not None:
                    right, j = trailing
                else:
                    right = Head.NONE
            if line == LineKind.SOLID:
                line = _line_kind(op2)
            return left, right, line, _non_empty(clean_label(text)), j

    return left, right, line, None, i


def _line_kind(op: str) -> LineKind:
    if "=" in op:
        return LineKind.THICK
    if "." in op:
        return LineKind.DOTTED
    return LineKind.SOLID


def _trailing_head(chars: str, i: int) -> tuple[Head, int] | None:
    if i >= len(chars):
        return None
    c = chars[i]
    if c == "o":
        head = Head.CIRCLE
    elif c == "x":
        head = Head.CROSS
    else:
        return None
    if i + 1 >= len(chars) or chars[i + 1] in " \t|&;":
        return head, i + 1
    return None


# ---------------------------------------------------------------------------
# State diagram parsing
# ---------------------------------------------------------------------------

_STATE_SKIP = {"classdef", "class", "hide", "scale", "}", "--"}


def parse_state(src: str) -> Graph | None:
    statements = _statements(src)
    if not statements:
        return None
    if not _first_word_of(statements[0]).lower().startswith("statediagram"):
        return None

    graph = Graph(direction=Dir.DOWN)
    in_note = False
    for st in statements[1:]:
        if in_note:
            if st.lower() == "end note":
                in_note = False
            continue
        words = st.split()
        first = words[0].lower() if words else ""
        if first == "direction":
            graph.direction = _parse_dir(words[1] if len(words) > 1 else "")
        elif first == "note":
            if ":" not in st:
                in_note = True
        elif first == "state":
            if not _parse_state_decl(st, graph):
                return None
        elif first in _STATE_SKIP:
            pass
        elif "-->" in st:
            if not _parse_transition(st, graph):
                return None
        elif not _parse_state_desc(st, graph):
            return None
        if graph.over_cap:
            return None

    if not graph.nodes:
        return None
    return graph


def _parse_state_decl(st: str, graph: Graph) -> bool:
    rest = st[len("state") :].strip().rstrip("{").strip()
    if not rest:
        return True
    if rest.startswith('"'):
        quoted = rest[1:]
        if '"' not in quoted:
            return False
        label, after = quoted.split('"', 1)
        after = after.strip()
        state_id = after[len("as") :].strip() if after.startswith("as") else label
        return graph.node_label(state_id, decode_html_entities(label)) is not None
    shape = Shape.ROUND
    state_id = rest
    stereotyped = False
    pos = rest.find("<<")
    if pos != -1:
        stereo = rest[pos + 2 :]
        while stereo.endswith(">>"):
            stereo = stereo[:-2]
        if stereo.strip() == "choice":
            shape = Shape.DIAMOND
        state_id = rest[:pos].strip()
        stereotyped = True
    if not state_id or _has_ws(state_id):
        return False
    label = state_id if stereotyped else None
    return graph.node_index(state_id, label, shape) is not None


def _parse_transition(st: str, graph: Graph) -> bool:
    rest = st
    prev: int | None = None
    while "-->" in rest:
        lhs, rhs = rest.split("-->", 1)
        from_id = lhs.rstrip().rstrip("-").strip()
        if prev is not None:
            if from_id:
                return False
            src = prev
        else:
            if not from_id:
                return False
            maybe_src = _state_endpoint(graph, from_id, True)
            if maybe_src is None:
                return False
            src = maybe_src
        if "-->" in rhs:
            to_part = rhs.split("-->", 1)[0]
            tail = rhs[len(to_part) :]
        else:
            to_part, tail = rhs, ""
        label: str | None = None
        if ":" in to_part:
            to_part, label_part = to_part.split(":", 1)
            label = _non_empty(decode_html_entities(label_part.strip()))
        to_id = to_part.lstrip().lstrip(">").rstrip().rstrip("-").strip()
        if not to_id:
            return False
        dst = _state_endpoint(graph, to_id, False)
        if dst is None:
            return False
        if len(graph.edges) >= MAX_EDGES:
            graph.over_cap = True
            return True
        graph.edges.append(Edge(src, dst, label, Head.ARROW, Head.NONE, LineKind.SOLID))
        prev = dst
        rest = tail
    return True


def _state_endpoint(graph: Graph, state_id: str, is_source: bool) -> int | None:
    if state_id == "[*]":
        key = "[*]start" if is_source else "[*]end"
        return graph.node_index(key, "●", Shape.ROUND)
    return graph.node_index(state_id, None, Shape.ROUND)


def _parse_state_desc(st: str, graph: Graph) -> bool:
    if ":" in st:
        state_id, desc = st.split(":", 1)
        state_id = state_id.strip()
        desc = desc.strip()
        if not state_id or _has_ws(state_id) or not desc:
            return False
        return graph.node_label(state_id, decode_html_entities(desc)) is not None
    if not _has_ws(st):
        return graph.node_index(st, None, Shape.ROUND) is not None
    return False


# ---------------------------------------------------------------------------
# Class / ER diagram parsing
# ---------------------------------------------------------------------------

MAX_MEMBERS = 8
CLASS_OPS: tuple[tuple[str, Head, Head, LineKind], ...] = (
    ("<|--", Head.TRIANGLE, Head.NONE, LineKind.SOLID),
    ("--|>", Head.NONE, Head.TRIANGLE, LineKind.SOLID),
    ("<|..", Head.TRIANGLE, Head.NONE, LineKind.DOTTED),
    ("..|>", Head.NONE, Head.TRIANGLE, LineKind.DOTTED),
    ("*--", Head.DIAMOND_FILL, Head.NONE, LineKind.SOLID),
    ("--*", Head.NONE, Head.DIAMOND_FILL, LineKind.SOLID),
    ("o--", Head.DIAMOND_OPEN, Head.NONE, LineKind.SOLID),
    ("--o", Head.NONE, Head.DIAMOND_OPEN, LineKind.SOLID),
    ("<--", Head.ARROW, Head.NONE, LineKind.SOLID),
    ("-->", Head.NONE, Head.ARROW, LineKind.SOLID),
    ("<..", Head.ARROW, Head.NONE, LineKind.DOTTED),
    ("..>", Head.NONE, Head.ARROW, LineKind.DOTTED),
    ("--", Head.NONE, Head.NONE, LineKind.SOLID),
    ("..", Head.NONE, Head.NONE, LineKind.DOTTED),
)


@dataclass
class ClassInfo:
    annotation: str | None = None
    attrs: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)


_CLASS_SKIP = {"note", "callback", "click", "link", "style", "cssclass", "classdef", "namespace", "}"}


def parse_class(src: str) -> tuple[Graph, list[ClassInfo]] | None:
    statements = _statements(src)
    if not statements:
        return None
    if not _first_word_of(statements[0]).lower().startswith("classdiagram"):
        return None

    graph = Graph(direction=Dir.DOWN)
    infos: list[ClassInfo] = []
    cur_class: int | None = None

    for st in statements[1:]:
        if cur_class is not None:
            if st == "}":
                cur_class = None
            else:
                push_member(infos[cur_class], st)
            continue
        words = st.split()
        first = words[0].lower() if words else ""
        if first == "direction":
            graph.direction = _parse_dir(words[1] if len(words) > 1 else "")
            continue
        if first in _CLASS_SKIP:
            continue
        if first == "class":
            rest = st[len("class") :].strip()
            if rest.endswith("{"):
                name, opened = rest[:-1].strip(), True
            else:
                name, opened = rest, False
            if not name or _has_ws(name):
                return None
            idx = graph.node_index(name, None, Shape.RECT)
            if idx is None:
                return None
            _sync_infos(graph, infos)
            if opened:
                cur_class = idx
            continue
        if st.startswith("<<"):
            body = st[2:]
            if ">>" not in body:
                return None
            ann, rest = body.split(">>", 1)
            name = rest.strip()
            if not name or _has_ws(name):
                return None
            idx = graph.node_index(name, None, Shape.RECT)
            if idx is None:
                return None
            _sync_infos(graph, infos)
            infos[idx].annotation = ann.strip()
            continue
        relation = _parse_class_relation(st)
        if relation is not None:
            from_name, to_name, head_from, head_to, line, label = relation
            f = graph.node_index(from_name, None, Shape.RECT)
            if f is None:
                return None
            _sync_infos(graph, infos)
            t = graph.node_index(to_name, None, Shape.RECT)
            if t is None:
                return None
            _sync_infos(graph, infos)
            if len(graph.edges) >= MAX_EDGES:
                return None
            graph.edges.append(Edge(f, t, label, head_to, head_from, line))
            continue
        if ":" in st:
            class_id, member = st.split(":", 1)
            class_id = class_id.strip()
            member = member.strip()
            if not class_id or _has_ws(class_id) or not member:
                return None
            idx = graph.node_index(class_id, None, Shape.RECT)
            if idx is None:
                return None
            _sync_infos(graph, infos)
            push_member(infos[idx], member)
            continue
        return None

    if not graph.nodes:
        return None
    _sync_infos(graph, infos)
    return graph, infos


def _sync_infos(graph: Graph, infos: list[ClassInfo]) -> None:
    while len(infos) < len(graph.nodes):
        infos.append(ClassInfo())


def push_member(info: ClassInfo, raw: str) -> None:
    if raw.startswith("<<"):
        body = raw[2:]
        if ">>" in body:
            info.annotation = body.split(">>", 1)[0].strip()
        return
    member = decode_html_entities(_display_generics(raw.strip()))
    target = info.methods if "(" in member else info.attrs
    if len(target) < MAX_MEMBERS:
        target.append(member)
    elif len(target) == MAX_MEMBERS:
        target.append("…")


def _parse_class_relation(st: str) -> tuple[str, str, Head, Head, LineKind, str | None] | None:
    n = len(st)
    found: tuple[int, str, Head, Head, LineKind] | None = None
    for pos in range(n):
        for op, hf, ht, line in CLASS_OPS:
            if not st.startswith(op, pos):
                continue
            if op.startswith("o") and pos > 0 and _is_id_char(st[pos - 1]):
                continue
            after = pos + len(op)
            if op.endswith("o") and after < n and _is_id_char(st[after]):
                continue
            found = (pos, op, hf, ht, line)
            break
        if found is not None:
            break
    if found is None:
        return None
    pos, op, head_from, head_to, line = found
    lhs = st[:pos].strip()
    rhs = st[pos + len(op) :].strip()

    lhs, card_from = _strip_cardinality_suffix(lhs)
    rhs, card_to = _strip_cardinality_prefix(rhs)
    rel_label: str | None = None
    if ":" in rhs:
        to_id, label_part = rhs.split(":", 1)
        to_id = to_id.strip()
        rel_label = _non_empty(decode_html_entities(label_part.strip()))
    else:
        to_id = rhs.strip()
    if not lhs or not to_id or _has_ws(lhs) or _has_ws(to_id):
        return None
    parts = [p for p in (card_from, rel_label or "", card_to) if p]
    return lhs, to_id, head_from, head_to, line, _non_empty(" ".join(parts))


def _strip_cardinality_suffix(s: str) -> tuple[str, str]:
    t = s.rstrip()
    if t.endswith('"'):
        rest = t[:-1]
        q = rest.rfind('"')
        if q != -1:
            return rest[:q].rstrip(), rest[q + 1 :]
    return t, ""


def _strip_cardinality_prefix(s: str) -> tuple[str, str]:
    t = s.lstrip()
    if t.startswith('"'):
        rest = t[1:]
        q = rest.find('"')
        if q != -1:
            return rest[q + 1 :].lstrip(), rest[:q]
    return t, ""


def _display_generics(s: str) -> str:
    out: list[str] = []
    opened = False
    for c in s:
        if c == "~":
            out.append(">" if opened else "<")
            opened = not opened
        else:
            out.append(c)
    return "".join(out)


def parse_er(src: str) -> tuple[Graph, list[ClassInfo]] | None:
    statements = _statements(src)
    if not statements:
        return None
    if _first_word_of(statements[0]).lower() != "erdiagram":
        return None

    graph = Graph(direction=Dir.DOWN)
    infos: list[ClassInfo] = []
    cur_entity: int | None = None

    for st in statements[1:]:
        if cur_entity is not None:
            if st == "}":
                cur_entity = None
            else:
                push_er_attribute(infos[cur_entity], st)
            continue
        split = _split_er_relationship(st)
        if split is not None:
            rel, label_part = split
            tokens = rel.split()
            if len(tokens) != 3:
                return None
            lhs, op, rhs = tokens
            parsed_op = parse_er_op(op)
            if parsed_op is None:
                return None
            card_l, card_r, line = parsed_op
            f = _er_entity(graph, infos, lhs)
            if f is None:
                return None
            t = _er_entity(graph, infos, rhs)
            if t is None:
                return None
            if len(graph.edges) >= MAX_EDGES:
                return None
            rel_label = clean_label(label_part) if label_part is not None else ""
            parts = [p for p in (card_l, rel_label, card_r) if p]
            graph.edges.append(Edge(f, t, _non_empty(" ".join(parts)), Head.NONE, Head.NONE, line))
            continue
        if st.endswith("{"):
            decl, opened = st[:-1].strip(), True
        else:
            decl, opened = st, False
        if not decl or len(decl.split()) != 1:
            return None
        idx = _er_entity(graph, infos, decl)
        if idx is None:
            return None
        if opened:
            cur_entity = idx

    if not graph.nodes:
        return None
    _sync_infos(graph, infos)
    return graph, infos


def _er_entity(graph: Graph, infos: list[ClassInfo], token: str) -> int | None:
    open_pos = token.find("[")
    if open_pos != -1:
        entity_id = token[:open_pos]
        label = clean_label(token[open_pos + 1 :].rstrip("]"))
        if not entity_id or not label:
            return None
        idx = graph.node_label(entity_id, label)
    else:
        idx = graph.node_index(token, None, Shape.RECT)
    if idx is None:
        return None
    _sync_infos(graph, infos)
    return idx


def _split_er_relationship(st: str) -> tuple[str, str | None] | None:
    label: str | None
    if ":" in st:
        rel, label_part = st.split(":", 1)
        label = label_part.strip()
    else:
        rel, label = st, None
    has_op = any(parse_er_op(tok) is not None for tok in rel.split())
    return (rel, label) if has_op else None


def parse_er_op(tok: str) -> tuple[str, str, LineKind] | None:
    if not tok.isascii() or len(tok) != 6:
        return None
    mid = tok[2:4]
    if mid == "--":
        line = LineKind.SOLID
    elif mid == "..":
        line = LineKind.DOTTED
    else:
        return None
    left = _er_card(tok[:2])
    right = _er_card(tok[4:6])
    if left is None or right is None:
        return None
    return left, right, line


_ER_CARDS: dict[str, str] = {
    "|o": "0..1",
    "o|": "0..1",
    "||": "1",
    "}o": "0..*",
    "o{": "0..*",
    "}|": "1..*",
    "|{": "1..*",
}


def _er_card(tok: str) -> str | None:
    return _ER_CARDS.get(tok)


def push_er_attribute(info: ClassInfo, raw: str) -> None:
    parts: list[str] = []
    for tok in raw.split():
        if tok.startswith('"'):
            break
        parts.append(tok)
    if not parts:
        return
    line = decode_html_entities(" ".join(parts))
    if len(info.attrs) < MAX_MEMBERS:
        info.attrs.append(line)
    elif len(info.attrs) == MAX_MEMBERS:
        info.attrs.append("…")


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------

U = 1
D = 2
L = 4
R = 8


class Cls(IntEnum):
    EMPTY = 0
    BORDER = 1
    TEXT = 2
    EDGE = 3
    EDGE_LABEL = 4


STY_DOT = 1
STY_THICK = 2
STY_SOLID = 4


class Canvas:
    """Character grid with per-cell class, junction mask and line style."""

    __slots__ = ("ch", "cls", "cur_style", "h", "mask", "occupied", "style", "w")

    def __init__(self, w: int, h: int) -> None:
        n = w * h
        self.w = w
        self.h = h
        self.ch: list[str] = [" "] * n
        self.cls: list[int] = [Cls.EMPTY] * n
        self.mask: list[int] = [0] * n
        self.style: list[int] = [0] * n
        self.occupied: list[bool] = [False] * n
        self.cur_style: int = STY_SOLID

    def idx(self, x: int, y: int) -> int:
        return y * self.w + x

    def _inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def set(self, x: int, y: int, c: str, cls: int) -> None:
        if not self._inside(x, y):
            return
        i = y * self.w + x
        self.ch[i] = c
        self.cls[i] = cls

    def add_bits(self, x: int, y: int, bits: int) -> None:
        if not self._inside(x, y):
            return
        i = y * self.w + x
        if self.occupied[i]:
            return
        self.mask[i] |= bits
        self.style[i] |= self.cur_style
        if self.cls[i] != Cls.BORDER:
            self.cls[i] = Cls.EDGE

    def blit(self, sub: Canvas, ox: int, oy: int) -> None:
        for sy in range(sub.h):
            for sx in range(sub.w):
                x, y = ox + sx, oy + sy
                if not self._inside(x, y):
                    continue
                si = sub.idx(sx, sy)
                di = self.idx(x, y)
                self.ch[di] = sub.ch[si]
                self.cls[di] = sub.cls[si]
                self.style[di] = sub.style[si]
                self.occupied[di] = True

    def junction(self, x: int, y: int, bits: int) -> None:
        if not self._inside(x, y):
            return
        i = y * self.w + x
        self.mask[i] |= bits
        if self.cls[i] != Cls.BORDER:
            self.cls[i] = Cls.EDGE

    def seg_v(self, x: int, y0: int, y1: int) -> None:
        a, b = min(y0, y1), max(y0, y1)
        for y in range(a, b + 1):
            bits = 0
            if y > a:
                bits |= U
            if y < b:
                bits |= D
            self.add_bits(x, y, bits)

    def seg_h(self, y: int, x0: int, x1: int) -> None:
        a, b = min(x0, x1), max(x0, x1)
        for x in range(a, b + 1):
            bits = 0
            if x > a:
                bits |= L
            if x < b:
                bits |= R
            self.add_bits(x, y, bits)

    def finalize_mask(self) -> None:
        ch = self.ch
        mask = self.mask
        style = self.style
        for i in range(len(ch)):
            m = mask[i]
            if m != 0 and ch[i] == " ":
                c = _mask_char(m)
                st = style[i]
                if st == STY_DOT:
                    c = _dotted_char(c)
                elif st == STY_THICK:
                    c = _thick_char(c)
                ch[i] = c

    def flip_vertical(self) -> None:
        """Mirror top-to-bottom for `BT`.

        Rows reorder; within-row text is unaffected, so labels stay readable.
        Box-drawing glyphs flip too.
        """
        for y in range(self.h // 2):
            y2 = self.h - 1 - y
            for x in range(self.w):
                i, j = self.idx(x, y), self.idx(x, y2)
                self.ch[i], self.ch[j] = self.ch[j], self.ch[i]
                self.cls[i], self.cls[j] = self.cls[j], self.cls[i]
        self.ch = [_flip_glyph_v(c) for c in self.ch]

    def flip_horizontal(self) -> None:
        """Mirror left-to-right for `RL`.

        Mirroring reverses each row, so after flipping glyphs we reverse each
        text/label run back to reading order.
        """
        for y in range(self.h):
            for x in range(self.w // 2):
                x2 = self.w - 1 - x
                i, j = self.idx(x, y), self.idx(x2, y)
                self.ch[i], self.ch[j] = self.ch[j], self.ch[i]
                self.cls[i], self.cls[j] = self.cls[j], self.cls[i]
        self.ch = [_flip_glyph_h(c) for c in self.ch]
        for y in range(self.h):
            x = 0
            while x < self.w:
                cls = self.cls[self.idx(x, y)]
                if cls in (Cls.TEXT, Cls.EDGE_LABEL):
                    start = self.idx(x, y)
                    while x < self.w and self.cls[self.idx(x, y)] == cls:
                        x += 1
                    end = self.idx(x, y)
                    self.ch[start:end] = self.ch[start:end][::-1]
                else:
                    x += 1

    def to_lines(self, styles: MermaidStyles) -> tuple[list[Text], list[str]]:
        styled: list[Text] = []
        plain: list[str] = []
        for y in range(self.h):
            row_start = y * self.w
            last = 0
            for x in range(self.w - 1, -1, -1):
                c = self.ch[row_start + x]
                if c != " " and c != CONT:
                    last = x + 1
                    break
            text = Text(no_wrap=True)
            plain_row: list[str] = []
            run: list[str] = []
            run_cls = int(Cls.EMPTY)
            for x in range(last):
                i = row_start + x
                c = self.ch[i]
                if c == CONT:
                    continue
                cls = self.cls[i]
                plain_row.append(c)
                if cls != run_cls and run:
                    text.append("".join(run), _style_for(run_cls, styles))
                    run = []
                run_cls = cls
                run.append(c)
            if run:
                text.append("".join(run), _style_for(run_cls, styles))
            styled.append(text)
            plain.append("".join(plain_row).rstrip())
        return styled, plain


def _style_for(cls: int, styles: MermaidStyles) -> Style | None:
    if cls == Cls.BORDER:
        return styles.border
    if cls == Cls.TEXT:
        return styles.node_text
    if cls == Cls.EDGE:
        return styles.edge
    if cls == Cls.EDGE_LABEL:
        return styles.edge_label
    return None


_MASK_CHARS: dict[int, str] = {
    U: "│",
    D: "│",
    U | D: "│",
    L: "─",
    R: "─",
    L | R: "─",
    D | R: "┌",
    D | L: "┐",
    U | R: "└",
    U | L: "┘",
    U | D | R: "├",
    U | D | L: "┤",
    D | L | R: "┬",
    U | L | R: "┴",
}


def _mask_char(mask: int) -> str:
    if mask == 0:
        return " "
    return _MASK_CHARS.get(mask, "┼")


_DOTTED: dict[str, str] = {"─": "╌", "│": "╎"}
_THICK: dict[str, str] = {
    "─": "━",
    "│": "┃",
    "┌": "┏",
    "┐": "┓",
    "└": "┗",
    "┘": "┛",
    "├": "┣",
    "┤": "┫",
    "┬": "┳",
    "┴": "┻",
    "┼": "╋",
}
_FLIP_V: dict[str, str] = {
    "┌": "└",
    "└": "┌",
    "┐": "┘",
    "┘": "┐",
    "┏": "┗",
    "┗": "┏",
    "┓": "┛",
    "┛": "┓",
    "╭": "╰",
    "╰": "╭",
    "╮": "╯",
    "╯": "╮",
    "┬": "┴",
    "┴": "┬",
    "┳": "┻",
    "┻": "┳",
    "▼": "▲",
    "▲": "▼",
    "▽": "△",
    "△": "▽",
}
_FLIP_H: dict[str, str] = {
    "┌": "┐",
    "┐": "┌",
    "└": "┘",
    "┘": "└",
    "┏": "┓",
    "┓": "┏",
    "┗": "┛",
    "┛": "┗",
    "╭": "╮",
    "╮": "╭",
    "╰": "╯",
    "╯": "╰",
    "├": "┤",
    "┤": "├",
    "┣": "┫",
    "┫": "┣",
    "▶": "◄",
    "◄": "▶",
    "▷": "◁",
    "◁": "▷",
}


def _dotted_char(c: str) -> str:
    return _DOTTED.get(c, c)


def _thick_char(c: str) -> str:
    return _THICK.get(c, c)


def _flip_glyph_v(c: str) -> str:
    return _FLIP_V.get(c, c)


def _flip_glyph_h(c: str) -> str:
    return _FLIP_H.get(c, c)


def _flip_for_direction(canvas: Canvas, direction: Dir) -> None:
    if direction is Dir.UP:
        canvas.flip_vertical()
    elif direction is Dir.LEFT:
        canvas.flip_horizontal()


# ---------------------------------------------------------------------------
# Flowchart layout
# ---------------------------------------------------------------------------


@dataclass
class Placed:
    x: int
    y: int
    w: int
    h: int
    cx: int
    cy: int
    rank: int


@dataclass
class _NodeSizes:
    box_w: list[int]
    box_h: list[int]
    lay_w: list[int]
    lay_h: list[int]
    extra_h: list[int]
    self_label_w: list[int]


@dataclass
class _Frame:
    """Node drawn as a titled frame around a pre-rendered sub-canvas (subgraph)."""

    sub: Canvas


@dataclass
class _Compartments:
    """Node drawn as a class/entity box with ruled sections."""

    sections: list[list[str]]


# `None` means a plain labelled box.
NodeExtra = _Frame | _Compartments | None


def _art_from_canvas(canvas: Canvas, styles: MermaidStyles) -> MermaidArt:
    styled, plain = canvas.to_lines(styles)
    return MermaidArt(styled, plain)


def _layout_flowchart(graph: Graph, styles: MermaidStyles, max_width: int | None) -> MermaidArt:
    extras: list[NodeExtra] = [None] * len(graph.nodes)
    canvas = _layout_canvas(graph, extras, max_width)
    _flip_for_direction(canvas, graph.direction)
    return _art_from_canvas(canvas, styles)


def _render_class(graph: Graph, infos: list[ClassInfo], styles: MermaidStyles, max_width: int | None) -> MermaidArt:
    extras: list[NodeExtra] = []
    for node, info in zip(graph.nodes, infos, strict=False):
        title: list[str] = []
        if info.annotation is not None:
            title.append(f"«{info.annotation}»")
        title.append(_display_generics(node.label))
        extras.append(_Compartments([title, list(info.attrs), list(info.methods)]))
    canvas = _layout_canvas(graph, extras, max_width)
    _flip_for_direction(canvas, graph.direction)
    return _art_from_canvas(canvas, styles)


_LINE_STYLE_BITS: dict[LineKind, int] = {
    LineKind.SOLID: STY_SOLID,
    LineKind.DOTTED: STY_DOT,
    LineKind.THICK: STY_THICK,
}


def _layout_canvas(graph: Graph, extras: list[NodeExtra], max_width: int | None) -> Canvas:
    n = len(graph.nodes)
    if n == 0:
        raise _OversizeError(Oversize.CELLS)

    ranks = compute_ranks(graph)
    max_rank = max(ranks) if ranks else 0

    by_rank: list[list[int]] = [[] for _ in range(max_rank + 1)]
    for idx, r in enumerate(ranks):
        by_rank[r].append(idx)
    order_ranks(by_rank, graph.edges, ranks)

    wrapped = [wrap_label(node.label, WRAP_WIDTH, MAX_LINES) for node in graph.nodes]
    box_w: list[int] = []
    box_h: list[int] = []
    for i in range(n):
        extra = extras[i]
        if isinstance(extra, _Frame):
            title_w = cell_len(_fit_label(graph.nodes[i].label, WRAP_WIDTH))
            box_w.append(max(extra.sub.w + 2, title_w + 4))
            box_h.append(extra.sub.h + 2)
        elif isinstance(extra, _Compartments):
            widest = max((cell_len(line) for section in extra.sections for line in section), default=1)
            box_w.append(max(widest, 1) + 2 * PAD + 2)
            filled = sum(1 for section in extra.sections if section)
            box_h.append(sum(len(section) for section in extra.sections) + max(filled - 1, 0) + 2)
        else:
            widest = max((cell_len(line) for line in wrapped[i]), default=1)
            box_w.append(max(widest, 1) + 2 * PAD + 2)
            box_h.append(len(wrapped[i]) + 2)

    extra_h = [0] * n
    self_label_w = [0] * n
    for e in graph.edges:
        if e.src == e.dst:
            extra_h[e.src] = 2
            if e.label is not None:
                self_label_w[e.src] = max(self_label_w[e.src], min(cell_len(e.label), MAX_LABEL))
    for i in range(n):
        if extra_h[i] > 0:
            box_w[i] = max(box_w[i], 7)
    lay_w = [box_w[i] + (2 * (self_label_w[i] + 3) if self_label_w[i] > 0 else 0) for i in range(n)]
    lay_h = [box_h[i] + extra_h[i] for i in range(n)]
    sizes = _NodeSizes(box_w, box_h, lay_w, lay_h, extra_h, self_label_w)

    placed = [Placed(0, 0, 0, 0, 0, 0, 0) for _ in range(n)]

    # BT/RL reuse the TD/LR layout, then flip the finished canvas (so text
    # stays readable) into the bottom-up / right-to-left orientation.
    vertical = graph.direction in (Dir.DOWN, Dir.UP)
    if vertical:
        plan = _place_td(ranks, max_rank, by_rank, sizes, graph, placed)
    else:
        plan = _place_lr(ranks, max_rank, by_rank, sizes, graph, placed)
    canvas_w, canvas_h = plan.canvas

    if max_width is not None and canvas_w > max_width:
        raise _OversizeError(Oversize.WIDTH)
    if canvas_w * canvas_h > MAX_CANVAS_CELLS:
        raise _OversizeError(Oversize.CELLS)

    canvas = Canvas(canvas_w, canvas_h)
    for idx in range(n):
        extra = extras[idx]
        if isinstance(extra, _Frame):
            _draw_frame(canvas, placed[idx], graph.nodes[idx].label, extra.sub)
        elif isinstance(extra, _Compartments):
            _draw_class_box(canvas, placed[idx], extra.sections)
        else:
            _draw_box(canvas, placed[idx], wrapped[idx], graph.nodes[idx].shape)
    for i, edge in enumerate(graph.edges):
        canvas.cur_style = _LINE_STYLE_BITS[edge.line]
        if edge.src == edge.dst:
            _route_self(canvas, placed[edge.src], edge)
            continue
        frm, to = placed[edge.src], placed[edge.dst]
        adjacent = to.rank == frm.rank + 1
        bus = plan.band_end[frm.rank] + plan.edge_bus[i]
        lane = plan.lane_base + plan.edge_lane[i]
        if vertical and adjacent:
            _route_forward(canvas, frm, to, edge, bus)
        elif vertical:
            _route_back(canvas, frm, to, edge, lane)
        elif adjacent:
            _route_forward_lr(canvas, frm, to, edge, bus)
        else:
            _route_back_lr(canvas, frm, to, edge, lane)

    canvas.finalize_mask()
    return canvas


# Items inside a subgraph scope: (kind, index). Groups become framed proxy nodes.
_ITEM_NODE = 0
_ITEM_GROUP = 1
_Item = tuple[int, int]


def _render_grouped(graph: Graph, styles: MermaidStyles, max_width: int | None) -> MermaidArt:
    proxy: dict[int, int] = {}
    for gi, g in enumerate(graph.groups):
        ni = graph.index.get(g.key)
        if ni is not None:
            proxy[ni] = gi

    def group_chain(g: int | None) -> list[int]:
        chain: list[int] = []
        cur = g
        while cur is not None:
            chain.append(cur)
            cur = graph.groups[cur].parent
        chain.reverse()
        return chain

    def endpoint(node: int) -> tuple[_Item, list[int]]:
        gi = proxy.get(node)
        if gi is not None:
            return (_ITEM_GROUP, gi), group_chain(graph.groups[gi].parent)
        return (_ITEM_NODE, node), group_chain(graph.node_group[node])

    scope_edges: dict[int | None, list[tuple[_Item, _Item, int]]] = {}
    referenced = [False] * len(graph.groups)
    for ei, e in enumerate(graph.edges):
        item_f, chain_f = endpoint(e.src)
        item_t, chain_t = endpoint(e.dst)
        k = 0
        for a, b in zip(chain_f, chain_t, strict=False):
            if a != b:
                break
            k += 1
        scope = None if k == 0 else chain_f[k - 1]
        f: _Item = (_ITEM_GROUP, chain_f[k]) if len(chain_f) > k else item_f
        t: _Item = (_ITEM_GROUP, chain_t[k]) if len(chain_t) > k else item_t
        if f[0] == _ITEM_GROUP:
            referenced[f[1]] = True
        if t[0] == _ITEM_GROUP:
            referenced[t[1]] = True
        scope_edges.setdefault(scope, []).append((f, t, ei))

    direct_nodes: dict[int | None, list[int]] = {}
    for ni, g in enumerate(graph.node_group):
        if ni not in proxy:
            direct_nodes.setdefault(g, []).append(ni)
    keep = [False] * len(graph.groups)
    for gi in range(len(graph.groups) - 1, -1, -1):
        has_nodes = bool(direct_nodes.get(gi))
        has_children = any(graph.groups[c].parent == gi and keep[c] for c in range(len(graph.groups)))
        keep[gi] = has_nodes or has_children or referenced[gi]

    canvas = _build_scope(graph, None, scope_edges, direct_nodes, keep, max_width)
    _flip_for_direction(canvas, graph.direction)
    return _art_from_canvas(canvas, styles)


def _build_scope(
    graph: Graph,
    scope: int | None,
    scope_edges: dict[int | None, list[tuple[_Item, _Item, int]]],
    direct_nodes: dict[int | None, list[int]],
    keep: list[bool],
    max_width: int | None,
) -> Canvas:
    items: list[_Item] = [(_ITEM_NODE, ni) for ni in direct_nodes.get(scope, [])]
    child_groups = [gi for gi in range(len(graph.groups)) if graph.groups[gi].parent == scope and keep[gi]]
    items.extend((_ITEM_GROUP, gi) for gi in child_groups)

    if not items:
        return Canvas(1, 1)

    index_of: dict[_Item, int] = {}
    nodes: list[Node] = []
    extras: list[NodeExtra] = []
    for item in items:
        index_of[item] = len(nodes)
        kind, idx = item
        if kind == _ITEM_NODE:
            nodes.append(Node(graph.nodes[idx].label, graph.nodes[idx].shape))
            extras.append(None)
        else:
            sub = _build_scope(graph, idx, scope_edges, direct_nodes, keep, None)
            nodes.append(Node(graph.groups[idx].label, Shape.RECT))
            extras.append(_Frame(sub))

    edges: list[Edge] = []
    for f, t, ei in scope_edges.get(scope, []):
        fi = index_of.get(f)
        ti = index_of.get(t)
        if fi is None or ti is None:
            continue
        e = graph.edges[ei]
        edges.append(Edge(fi, ti, e.label, e.head_to, e.head_from, e.line))

    synth = Graph(nodes=nodes, edges=edges, direction=graph.direction)
    return _layout_canvas(synth, extras, max_width)


def _draw_class_box(canvas: Canvas, p: Placed, sections: list[list[str]]) -> None:
    _draw_box(canvas, p, [], Shape.RECT)
    inner = max(p.w - (2 * PAD + 2), 1)
    row = p.y + 1
    first = True
    for si, section in enumerate(sections):
        if not section:
            continue
        if not first:
            canvas.set(p.x, row, "├", Cls.BORDER)
            for x in range(p.x + 1, p.x + p.w - 1):
                canvas.set(x, row, "─", Cls.BORDER)
            canvas.set(p.x + p.w - 1, row, "┤", Cls.BORDER)
            row += 1
        first = False
        for line in section:
            text = _fit_label(line, inner)
            # The title section is centered; attributes and methods are left-aligned.
            tx = p.x + 1 + PAD + (max(inner - cell_len(text), 0) // 2 if si == 0 else 0)
            _draw_seq_text(canvas, text, tx, row, Cls.TEXT)
            row += 1


def _draw_frame(canvas: Canvas, p: Placed, title: str, sub: Canvas) -> None:
    _draw_box(canvas, p, [], Shape.RECT)
    t = _fit_label(title, max(p.w - 4, 0))
    _draw_seq_text(canvas, f" {t} ", p.x + 1, p.y, Cls.TEXT)
    ox = p.x + 1 + (p.w - 2 - sub.w) // 2
    oy = p.y + 1 + (p.h - 2 - sub.h) // 2
    canvas.blit(sub, ox, oy)


_Span = tuple[int, int, int, int, int]


def _bus_spans_td(graph: Graph, ranks: list[int], centers: list[int], r: int, exact: bool) -> list[_Span]:
    spans: list[_Span] = []
    for i, e in enumerate(graph.edges):
        jogs = centers[e.src] != centers[e.dst] if exact else abs(centers[e.src] - centers[e.dst]) > 1
        if e.src != e.dst and ranks[e.src] == r and ranks[e.dst] == r + 1 and jogs:
            a = min(centers[e.src], centers[e.dst])
            b = max(centers[e.src], centers[e.dst])
            spans.append((a, b, e.src, e.dst, i))
    return spans


def _lane_spans(graph: Graph, ranks: list[int], placed: list[Placed], vertical: bool) -> list[_Span]:
    spans: list[_Span] = []
    for i, e in enumerate(graph.edges):
        if e.src == e.dst or ranks[e.dst] == ranks[e.src] + 1:
            continue
        pf, pt = placed[e.src], placed[e.dst]
        if vertical:
            a, b = min(pf.cy, pt.cy), max(pf.cy, pt.cy)
        else:
            a, b = min(pf.cx, pt.cx), max(pf.cx, pt.cx)
        spans.append((a, b, e.src, e.dst, i))
    return spans


@dataclass
class _RoutePlan:
    canvas: tuple[int, int]
    band_end: list[int]
    edge_bus: list[int]
    lane_base: int
    edge_lane: list[int]


def _place_td(
    ranks: list[int],
    max_rank: int,
    by_rank: list[list[int]],
    sizes: _NodeSizes,
    graph: Graph,
    placed: list[Placed],
) -> _RoutePlan:
    centers = assign_positions(by_rank, sizes.lay_w, GAP_X, graph.edges, ranks)

    edge_bus = [0] * len(graph.edges)
    bus_tracks = [0] * (max_rank + 1)
    for r in range(max_rank):
        spans = _bus_spans_td(graph, ranks, centers, r, False)
        if not spans:
            continue
        assigned, count = assign_tracks(spans)
        for idx, slot in assigned:
            edge_bus[idx] = slot
        bus_tracks[r] = count

    rank_h = [max((sizes.box_h[i] + sizes.extra_h[i] for i in row), default=3) for row in by_rank]
    rank_y = [0] * (max_rank + 1)
    for r in range(1, max_rank + 1):
        gap = max(GAP_Y, bus_tracks[r - 1] + 1)
        rank_y[r] = rank_y[r - 1] + rank_h[r - 1] + gap
    canvas_h = rank_y[max_rank] + rank_h[max_rank]
    band_end = [rank_y[r] + rank_h[r] for r in range(max_rank + 1)]

    diagram_w = 1
    for r, row in enumerate(by_rank):
        for idx in row:
            w = sizes.box_w[idx]
            h = sizes.box_h[idx]
            cx = centers[idx]
            x = max(cx - w // 2, 0)
            y = rank_y[r] + (rank_h[r] - h - sizes.extra_h[idx]) // 2
            placed[idx] = Placed(x, y, w, h, cx, y + h // 2, r)
            diagram_w = max(diagram_w, x + w)
            if sizes.extra_h[idx] > 0 and sizes.self_label_w[idx] > 0:
                diagram_w = max(diagram_w, x + w + 2 + sizes.self_label_w[idx])

    content_w = diagram_w
    for e in graph.edges:
        if e.src == e.dst or e.label is None:
            continue
        lw = min(cell_len(e.label), MAX_LABEL)
        if ranks[e.dst] == ranks[e.src] + 1:
            content_w = max(content_w, placed[e.dst].cx + 2 + lw)
        else:
            content_w = max(content_w, diagram_w + lw + 1)

    edge_lane = [0] * len(graph.edges)
    lanes = _lane_spans(graph, ranks, placed, True)
    if not lanes:
        canvas_w, lane_base = content_w, 0
    else:
        assigned, count = assign_tracks(lanes)
        for idx, slot in assigned:
            edge_lane[idx] = slot
        canvas_w, lane_base = content_w + 1 + count, content_w + 1

    return _RoutePlan((canvas_w, canvas_h), band_end, edge_bus, lane_base, edge_lane)


def _place_lr(
    ranks: list[int],
    max_rank: int,
    by_rank: list[list[int]],
    sizes: _NodeSizes,
    graph: Graph,
    placed: list[Placed],
) -> _RoutePlan:
    col_w = [max((sizes.box_w[i] for i in row), default=0) for row in by_rank]

    max_label = 0
    for e in graph.edges:
        if e.label is None:
            continue
        if e.src == e.dst or ranks[e.dst] == ranks[e.src] + 1:
            max_label = max(max_label, min(cell_len(e.label), MAX_LABEL))
    base_gap = max(GAP_X + 1, max_label + 3)

    centers = assign_positions(by_rank, sizes.lay_h, 1, graph.edges, ranks)

    edge_bus = [0] * len(graph.edges)
    bus_tracks = [0] * (max_rank + 1)
    for r in range(max_rank):
        spans = _bus_spans_td(graph, ranks, centers, r, True)
        if not spans:
            continue
        assigned, count = assign_tracks(spans)
        for idx, slot in assigned:
            edge_bus[idx] = slot
        bus_tracks[r] = count

    rank_x = [0] * (max_rank + 1)
    for r in range(1, max_rank + 1):
        gap = max(base_gap, bus_tracks[r - 1] + 1)
        rank_x[r] = rank_x[r - 1] + col_w[r - 1] + gap
    self_tail = max(
        (2 + sizes.self_label_w[i] for i in by_rank[max_rank] if sizes.extra_h[i] > 0 and sizes.self_label_w[i] > 0),
        default=0,
    )
    canvas_w = rank_x[max_rank] + col_w[max_rank] + self_tail
    band_end = [rank_x[r] + col_w[r] for r in range(max_rank + 1)]

    diagram_h = 1
    for r, row in enumerate(by_rank):
        x = rank_x[r]
        for idx in row:
            w = sizes.box_w[idx]
            h = sizes.box_h[idx]
            cy = centers[idx]
            y = max(cy - (h + sizes.extra_h[idx]) // 2, 0)
            placed[idx] = Placed(x, y, w, h, x + w // 2, y + h // 2, r)
            diagram_h = max(diagram_h, y + h + sizes.extra_h[idx])

    edge_lane = [0] * len(graph.edges)
    lanes = _lane_spans(graph, ranks, placed, False)
    if not lanes:
        canvas_h, lane_base = diagram_h, 0
    else:
        assigned, count = assign_tracks(lanes)
        for idx, slot in assigned:
            edge_lane[idx] = slot
        canvas_h, lane_base = diagram_h + 1 + count, diagram_h + 1

    return _RoutePlan((canvas_w, canvas_h), band_end, edge_bus, lane_base, edge_lane)


def assign_tracks(spans: list[_Span]) -> tuple[list[tuple[int, int]], int]:
    """Pack (start, end, from, to, idx) spans into parallel tracks.

    Spans sharing a source or a target may share a track even when they overlap,
    because their wires merge; otherwise they need a one-cell gap.
    """
    tracks: list[list[tuple[int, int, int, int]]] = []
    out: list[tuple[int, int]] = []
    for s, e, f, t, idx in sorted(spans):
        slot = -1
        for ti, members in enumerate(tracks):
            if all(e2 + 2 <= s or e + 2 <= s2 or f2 == f or t2 == t for s2, e2, f2, t2 in members):
                slot = ti
                break
        if slot == -1:
            tracks.append([])
            slot = len(tracks) - 1
        tracks[slot].append((s, e, f, t))
        out.append((idx, slot))
    return out, len(tracks)


def order_ranks(by_rank: list[list[int]], edges: list[Edge], ranks: list[int]) -> None:
    """Reorder nodes within each rank to minimize edge crossings.

    Sugiyama-style barycenter sweeps: alternate down/up passes sort each rank by
    the mean position of its forward neighbours, keeping the ordering with the
    fewest crossings between adjacent ranks.
    """
    n = len(ranks)
    if len(by_rank) < 2 or n < 3:
        return
    parents: list[list[int]] = [[] for _ in range(n)]
    children: list[list[int]] = [[] for _ in range(n)]
    for e in edges:
        if e.src != e.dst and ranks[e.dst] > ranks[e.src]:
            parents[e.dst].append(e.src)
            children[e.src].append(e.dst)

    pos = [0] * n
    for row in by_rank:
        for i, v in enumerate(row):
            pos[v] = i

    best = [row[:] for row in by_rank]
    best_crossings = count_crossings(edges, ranks, pos)
    if best_crossings == 0:
        return

    for it in range(8):
        if it % 2 == 0:
            for row in by_rank[1:]:
                _sort_by_barycenter(row, parents, pos)
                for i, v in enumerate(row):
                    pos[v] = i
        else:
            for row in reversed(by_rank[:-1]):
                _sort_by_barycenter(row, children, pos)
                for i, v in enumerate(row):
                    pos[v] = i
        crossings = count_crossings(edges, ranks, pos)
        if crossings < best_crossings:
            best_crossings = crossings
            best = [row[:] for row in by_rank]
        if best_crossings == 0:
            break

    for i, row in enumerate(best):
        by_rank[i] = row


def _sort_by_barycenter(row: list[int], neigh: list[list[int]], pos: list[int]) -> None:
    def key(v: int) -> float:
        if not neigh[v]:
            return float(pos[v])
        return sum(pos[u] for u in neigh[v]) / len(neigh[v])

    row.sort(key=key)


def count_crossings(edges: list[Edge], ranks: list[int], pos: list[int]) -> int:
    adjacent = [
        (ranks[e.src], pos[e.src], pos[e.dst]) for e in edges if e.src != e.dst and ranks[e.dst] == ranks[e.src] + 1
    ]
    crossings = 0
    for i, a in enumerate(adjacent):
        for b in adjacent[i + 1 :]:
            if a[0] == b[0] and ((a[1] < b[1] and a[2] > b[2]) or (a[1] > b[1] and a[2] < b[2])):
                crossings += 1
    return crossings


def assign_positions(
    by_rank: list[list[int]],
    size: list[int],
    sep: int,
    edges: list[Edge],
    ranks: list[int],
) -> list[int]:
    """Assign a center coordinate (along the cross-axis) to every node.

    Iterative barycenter relaxation: each node drifts toward the average of its
    forward neighbours while ranks keep order and a minimum `sep` between boxes,
    which straightens chains and centers branches.
    """
    n = len(size)
    parents: list[list[int]] = [[] for _ in range(n)]
    children: list[list[int]] = [[] for _ in range(n)]
    for e in edges:
        if e.src != e.dst and ranks[e.dst] > ranks[e.src]:
            parents[e.dst].append(e.src)
            children[e.src].append(e.dst)

    pos = [0.0] * n
    for row in by_rank:
        x = 0.0
        for v in row:
            half = size[v] / 2.0
            x += half
            pos[v] = x
            x += half + sep

    for it in range(10):
        if it % 2 == 0:
            for row in by_rank:
                _relax_rank(row, parents, pos, size, sep)
        else:
            for row in reversed(by_rank):
                _relax_rank(row, children, pos, size, sep)

    min_left = min((pos[v] - size[v] / 2.0 for v in range(n)), default=0.0)
    if not math.isfinite(min_left):
        min_left = 0.0
    # Rust `round()` rounds half away from zero; floor(x + 0.5) matches it for x >= 0.
    return [max(math.floor(pos[v] - min_left + 0.5), 0) for v in range(n)]


def _relax_rank(nodes: list[int], neigh: list[list[int]], pos: list[float], size: list[int], sep: int) -> None:
    n = len(nodes)
    if n == 0:
        return
    desired: list[float] = []
    for v in nodes:
        if not neigh[v]:
            desired.append(pos[v])
        else:
            desired.append(sum(pos[u] for u in neigh[v]) / len(neigh[v]))

    def half(i: int) -> float:
        return size[nodes[i]] / 2.0

    left = [0.0] * n
    right = [0.0] * n
    for i in range(n):
        left[i] = desired[i] if i == 0 else max(desired[i], left[i - 1] + half(i - 1) + sep + half(i))
    for i in range(n - 1, -1, -1):
        right[i] = desired[i] if i == n - 1 else min(desired[i], right[i + 1] - half(i + 1) - sep - half(i))
    for i in range(n):
        pos[nodes[i]] = (left[i] + right[i]) / 2.0
    for i in range(1, n):
        min_p = pos[nodes[i - 1]] + half(i - 1) + sep + half(i)
        if pos[nodes[i]] < min_p:
            pos[nodes[i]] = min_p


def _rfind_any(s: str, chars: str) -> int:
    return max(s.rfind(c) for c in chars)


def wrap_label(label: str, width: int, max_lines: int) -> list[str]:
    width = max(width, 1)
    lines: list[str] = []
    cur = ""
    cur_w = 0
    for word in label.split():
        ww = cell_len(word)
        if ww > width:
            if cur:
                lines.append(cur)
                cur = ""
            chunk = ""
            chunk_w = 0
            for ch in word:
                cw = _char_w1(ch)
                if chunk_w + cw > width and chunk:
                    # Prefer breaking after the last identifier boundary so a long
                    # token is not sliced mid-segment; fall back to a per-char break.
                    p = _rfind_any(chunk, LABEL_BREAK_CHARS)
                    if p != -1:
                        carry = chunk[p + 1 :]
                        chunk = chunk[: p + 1]
                    else:
                        carry = ""
                    lines.append(chunk)
                    chunk_w = sum(_char_w1(c) for c in carry)
                    chunk = carry
                chunk += ch
                chunk_w += cw
            cur = chunk
            cur_w = chunk_w
        elif not cur:
            cur = word
            cur_w = ww
        elif cur_w + 1 + ww <= width:
            cur += " " + word
            cur_w += 1 + ww
        else:
            lines.append(cur)
            cur = word
            cur_w = ww
    if cur:
        lines.append(cur)
    if not lines:
        lines.append("")
    if len(lines) > max_lines:
        del lines[max_lines:]
        target = max(width - 1, 1)
        s = ""
        sw = 0
        for ch in lines[-1]:
            cw = _char_w1(ch)
            if sw + cw > target:
                break
            s += ch
            sw += cw
        lines[-1] = s + "…"
    return lines


def _fit_label(label: str, inner: int) -> str:
    if cell_len(label) <= inner:
        return label
    out = ""
    used = 0
    for c in label:
        cw = _char_width(c)
        if used + cw + 1 > inner:
            break
        out += c
        used += cw
    return out + "…"


def _draw_box(canvas: Canvas, p: Placed, lines: list[str], shape: Shape) -> None:
    x, y, w, h = p.x, p.y, p.w, p.h
    right = x + w - 1
    bottom = y + h - 1

    if shape is Shape.RECT:
        tl, tr, bl, br = "┌", "┐", "└", "┘"
    else:
        tl, tr, bl, br = "╭", "╮", "╰", "╯"
    canvas.set(x, y, tl, Cls.BORDER)
    canvas.set(right, y, tr, Cls.BORDER)
    canvas.set(x, bottom, bl, Cls.BORDER)
    canvas.set(right, bottom, br, Cls.BORDER)

    for cx in range(x + 1, right):
        canvas.add_bits(cx, y, L | R)
        canvas.add_bits(cx, bottom, L | R)
    for cy in range(y + 1, bottom):
        canvas.add_bits(x, cy, U | D)
        canvas.add_bits(right, cy, U | D)

    for cy in range(y, bottom + 1):
        for cx in range(x, right + 1):
            if canvas._inside(cx, cy):
                canvas.occupied[canvas.idx(cx, cy)] = True

    inner = max(w - (2 * PAD + 2), 1)
    for li, line in enumerate(lines):
        row = y + 1 + li
        text = _fit_label(line, inner)
        tw = cell_len(text)
        cur = x + 1 + PAD + max(inner - tw, 0) // 2
        for c in text:
            cw = _char_w1(c)
            canvas.set(cur, row, c, Cls.TEXT)
            # Wide glyphs (CJK, emoji) own a second column; mark it as a
            # continuation so the line builder doesn't emit a stray space.
            for k in range(1, cw):
                canvas.set(cur + k, row, CONT, Cls.TEXT)
            cur += cw


def _route_forward(canvas: Canvas, frm: Placed, to: Placed, edge: Edge, bus: int) -> None:
    tx = to.cx
    bx = tx if abs(frm.cx - tx) <= 1 else frm.cx
    by = frm.y + frm.h - 1
    head_row = to.y - 1

    canvas.junction(bx, by, D)
    canvas.seg_v(bx, by, bus)
    if bx == tx:
        canvas.seg_v(bx, bus, head_row)
    else:
        canvas.seg_h(bus, bx, tx)
        canvas.seg_v(tx, bus, head_row)

    if edge.head_to is Head.NONE:
        canvas.add_bits(tx, head_row, U)
    else:
        canvas.set(tx, head_row, _head_glyph(edge.head_to, "▼"), Cls.EDGE)
    if edge.head_from is not Head.NONE:
        canvas.set(bx, by, _head_glyph(edge.head_from, "▲"), Cls.EDGE)

    if edge.label is not None:
        _place_label(canvas, edge.label, head_row, tx + 1)


_TRIANGLE_HEADS: dict[str, str] = {"▼": "▽", "▲": "△", "◄": "◁", "▶": "▷"}


def _head_glyph(head: Head, arrow: str) -> str:
    if head is Head.CIRCLE:
        return "o"
    if head is Head.CROSS:
        return "×"
    if head is Head.DIAMOND_FILL:
        return "◆"
    if head is Head.DIAMOND_OPEN:
        return "◇"
    if head is Head.TRIANGLE:
        return _TRIANGLE_HEADS.get(arrow, arrow)
    return arrow


def _route_self(canvas: Canvas, p: Placed, edge: Edge) -> None:
    bottom = p.y + p.h - 1
    exit_x = p.cx + 1
    ret_x = p.x + p.w - 2
    if ret_x <= exit_x or bottom + 2 >= canvas.h:
        return
    if edge.line is LineKind.DOTTED:
        v, h, bl, br = "╎", "╌", "╰", "╯"
    elif edge.line is LineKind.THICK:
        v, h, bl, br = "┃", "━", "┗", "┛"
    else:
        v, h, bl, br = "│", "─", "╰", "╯"
    canvas.junction(exit_x, bottom, D)
    canvas.set(exit_x, bottom + 1, v, Cls.EDGE)
    canvas.set(exit_x, bottom + 2, bl, Cls.EDGE)
    for x in range(exit_x + 1, ret_x):
        canvas.set(x, bottom + 2, h, Cls.EDGE)
    canvas.set(ret_x, bottom + 2, br, Cls.EDGE)
    canvas.set(ret_x, bottom + 1, _head_glyph(edge.head_to, "▲"), Cls.EDGE)
    if edge.label is not None:
        _place_label(canvas, edge.label, bottom + 1, p.x + p.w + 1)


def _route_back(canvas: Canvas, frm: Placed, to: Placed, edge: Edge, lane_x: int) -> None:
    sx = frm.x + frm.w - 1
    sy = frm.cy
    tx = to.x + to.w - 1
    tyc = to.cy

    canvas.junction(sx, sy, R)
    canvas.seg_h(sy, sx, lane_x)
    canvas.seg_v(lane_x, sy, tyc)
    canvas.seg_h(tyc, tx + 1, lane_x)

    if edge.head_to is Head.NONE:
        canvas.add_bits(tx + 1, tyc, R)
    else:
        canvas.set(tx + 1, tyc, _head_glyph(edge.head_to, "◄"), Cls.EDGE)
    if edge.head_from is not Head.NONE:
        canvas.set(sx, sy, _head_glyph(edge.head_from, "◄"), Cls.EDGE)

    if edge.label is not None:
        _place_label(canvas, edge.label, max(tyc - 1, 0), max(lane_x - (cell_len(edge.label) + 1), 0))


def _route_forward_lr(canvas: Canvas, frm: Placed, to: Placed, edge: Edge, bus: int) -> None:
    rx = frm.x + frm.w - 1
    ry = frm.cy
    ly = to.cy
    head_col = to.x - 1

    canvas.junction(rx, ry, R)
    canvas.seg_h(ry, rx, bus)
    if ry == ly:
        canvas.seg_h(ry, bus, head_col)
    else:
        canvas.seg_v(bus, ry, ly)
        canvas.seg_h(ly, bus, head_col)

    if edge.head_to is Head.NONE:
        canvas.add_bits(head_col, ly, R)
    else:
        canvas.set(head_col, ly, _head_glyph(edge.head_to, "▶"), Cls.EDGE)
    if edge.head_from is not Head.NONE:
        canvas.set(rx, ry, _head_glyph(edge.head_from, "◄"), Cls.EDGE)

    if edge.label is not None:
        _place_label(canvas, edge.label, max(ly - 1, 0), bus + 1)


def _route_back_lr(canvas: Canvas, frm: Placed, to: Placed, edge: Edge, lane_y: int) -> None:
    sx = frm.cx
    sy = frm.y + frm.h - 1
    tx = to.cx
    ty = to.y + to.h - 1

    canvas.junction(sx, sy, D)
    canvas.seg_v(sx, sy, lane_y)
    canvas.seg_h(lane_y, sx, tx)
    canvas.seg_v(tx, lane_y, ty + 1)

    if edge.head_to is Head.NONE:
        canvas.add_bits(tx, ty + 1, D)
    else:
        canvas.set(tx, ty + 1, _head_glyph(edge.head_to, "▲"), Cls.EDGE)
    if edge.head_from is not Head.NONE:
        canvas.set(sx, sy, _head_glyph(edge.head_from, "▲"), Cls.EDGE)

    if edge.label is not None:
        _place_label(canvas, edge.label, max(lane_y - 1, 0), (sx + tx) // 2)


def _place_label(canvas: Canvas, label: str, row: int, start_x: int) -> None:
    if row < 0 or row >= canvas.h or start_x < 0:
        return
    text = _fit_label(label, MAX_LABEL)
    x = start_x
    for c in text:
        cw = _char_w1(c)
        if x + cw > canvas.w:
            break
        blocked = False
        for k in range(cw):
            i = canvas.idx(x + k, row)
            if canvas.ch[i] != " " or canvas.mask[i] != 0 or canvas.occupied[i]:
                blocked = True
                break
        if blocked:
            break
        canvas.set(x, row, c, Cls.EDGE_LABEL)
        for k in range(1, cw):
            canvas.set(x + k, row, CONT, Cls.EDGE_LABEL)
        x += cw


def compute_ranks(graph: Graph) -> list[int]:
    """Longest-path ranks over a DFS-derived DAG (back edges are ignored)."""
    n = len(graph.nodes)
    children: list[list[int]] = [[] for _ in range(n)]
    indeg = [0] * n
    for e in graph.edges:
        if e.src != e.dst:
            children[e.src].append(e.dst)
            indeg[e.dst] += 1

    color = [0] * n
    dag: list[list[int]] = [[] for _ in range(n)]
    order: list[int] = []

    roots = [i for i in range(n) if indeg[i] == 0]
    for start in itertools.chain(roots, range(n)):
        if color[start] == 0:
            _dfs_dag(start, children, color, dag, order)

    rank = [0] * n
    for u in reversed(order):
        for v in dag[u]:
            rank[v] = max(rank[v], rank[u] + 1)
    return rank


def _dfs_dag(start: int, children: list[list[int]], color: list[int], dag: list[list[int]], order: list[int]) -> None:
    stack: list[tuple[int, int]] = [(start, 0)]
    color[start] = 1
    while stack:
        u, i = stack[-1]
        if i < len(children[u]):
            v = children[u][i]
            stack[-1] = (u, i + 1)
            if color[v] == 1:
                continue
            dag[u].append(v)
            if color[v] == 0:
                color[v] = 1
                stack.append((v, 0))
        else:
            color[u] = 2
            order.append(u)
            stack.pop()


# ---------------------------------------------------------------------------
# Sequence diagrams
# ---------------------------------------------------------------------------

SEQ_GAP = 5


class SeqHead(Enum):
    ARROW = "arrow"
    CROSS = "cross"


SEQ_OPS: tuple[tuple[str, bool, SeqHead], ...] = (
    ("-->>", True, SeqHead.ARROW),
    ("->>", False, SeqHead.ARROW),
    ("--x", True, SeqHead.CROSS),
    ("-x", False, SeqHead.CROSS),
    ("--)", True, SeqHead.ARROW),
    ("-)", False, SeqHead.ARROW),
    ("-->", True, SeqHead.ARROW),
    ("->", False, SeqHead.ARROW),
)


class NoteKind(Enum):
    OVER = "over"
    LEFT = "left"
    RIGHT = "right"


@dataclass
class NoteAnchor:
    kind: NoteKind
    a: int
    b: int


@dataclass
class SeqMessage:
    src: int
    dst: int
    text: str | None
    dashed: bool
    head: SeqHead


@dataclass
class SeqNote:
    anchor: NoteAnchor
    text: str


@dataclass
class SeqDivider:
    text: str


SeqItem = SeqMessage | SeqNote | SeqDivider


@dataclass
class SeqDiagram:
    labels: list[str] = field(default_factory=list)
    index: dict[str, int] = field(default_factory=dict)
    items: list[SeqItem] = field(default_factory=list)

    def participant(self, participant_id: str, label: str | None) -> int | None:
        existing = self.index.get(participant_id)
        if existing is not None:
            if label is not None:
                self.labels[existing] = label
            return existing
        if len(self.labels) >= MAX_NODES:
            return None
        self.index[participant_id] = len(self.labels)
        self.labels.append(label if label is not None else participant_id)
        return len(self.labels) - 1


_SEQ_SKIP = {
    "activate",
    "deactivate",
    "create",
    "destroy",
    "title",
    "acctitle",
    "accdescr",
    "links",
    "link",
    "properties",
}
_SEQ_BLOCK_OPEN = {"loop", "alt", "opt", "par", "critical", "break"}
_SEQ_BLOCK_BRANCH = {"else", "and", "option"}


def parse_sequence(src: str) -> SeqDiagram | None:
    statements = _statements(src)
    if not statements:
        return None
    if _first_word_of(statements[0]).lower() != "sequencediagram":
        return None

    seq = SeqDiagram()
    autonumber = False
    msg_count = 0
    blocks: list[bool] = []

    for st in statements[1:]:
        first = _first_word_of(st)
        lower = first.lower()
        if lower in ("participant", "actor"):
            rest = st[len(first) :].strip()
            if not rest:
                return None
            label: str | None = None
            if " as " in rest:
                participant_id, label_part = rest.split(" as ", 1)
                participant_id = participant_id.strip()
                label = clean_label(label_part)
            else:
                participant_id = rest
            if seq.participant(participant_id, label) is None:
                return None
        elif lower == "autonumber":
            autonumber = True
        elif lower in _SEQ_SKIP:
            pass
        elif lower == "note":
            rest = st[len(first) :].strip()
            parsed = _parse_note_anchor(rest, seq)
            if parsed is None:
                return None
            text_part, anchor = parsed
            if len(seq.items) >= MAX_EDGES:
                return None
            seq.items.append(SeqNote(anchor, text_part))
        elif lower in _SEQ_BLOCK_OPEN or lower in _SEQ_BLOCK_BRANCH:
            if lower in _SEQ_BLOCK_BRANCH:
                if not blocks or blocks[-1] is not True:
                    continue
            else:
                blocks.append(True)
            if len(seq.items) >= MAX_EDGES:
                return None
            seq.items.append(SeqDivider(decode_html_entities(st)))
        elif lower in ("rect", "box"):
            blocks.append(False)
        elif lower == "end":
            popped = blocks.pop() if blocks else None
            if popped is True:
                if len(seq.items) >= MAX_EDGES:
                    return None
                seq.items.append(SeqDivider("end"))
        else:
            message = _parse_seq_message(st, seq)
            if message is None:
                return None
            src_idx, dst_idx, text, dashed, head = message
            if autonumber:
                msg_count += 1
                text = f"{msg_count}. {text}" if text is not None else f"{msg_count}."
            if len(seq.items) >= MAX_EDGES:
                return None
            seq.items.append(SeqMessage(src_idx, dst_idx, text, dashed, head))

    if not seq.labels:
        return None
    return seq


def _parse_note_anchor(rest: str, seq: SeqDiagram) -> tuple[str, NoteAnchor] | None:
    lower = rest.lower()
    if lower.startswith("over "):
        ids_and_text, kind = rest[len("over ") :], NoteKind.OVER
    elif lower.startswith("left of "):
        ids_and_text, kind = rest[len("left of ") :], NoteKind.LEFT
    elif lower.startswith("right of "):
        ids_and_text, kind = rest[len("right of ") :], NoteKind.RIGHT
    else:
        return None
    if ":" not in ids_and_text:
        return None
    ids, text = ids_and_text.split(":", 1)
    text = decode_html_entities(text.strip())
    parts = [p.strip() for p in ids.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    a = seq.participant(parts[0], None)
    if a is None:
        return None
    if kind is NoteKind.OVER:
        if len(parts) > 1:
            b = seq.participant(parts[1], None)
            if b is None:
                return None
        else:
            b = a
        return text, NoteAnchor(NoteKind.OVER, min(a, b), max(a, b))
    return text, NoteAnchor(kind, a, a)


def _parse_seq_message(st: str, seq: SeqDiagram) -> tuple[int, int, str | None, bool, SeqHead] | None:
    found: tuple[int, str, bool, SeqHead] | None = None
    for pos in range(len(st)):
        for op, dashed, head in SEQ_OPS:
            if st.startswith(op, pos):
                found = (pos, op, dashed, head)
                break
        if found is not None:
            break
    if found is None:
        return None
    pos, op, dashed, head = found
    from_id = st[:pos].strip()
    if not from_id:
        return None
    rest = st[pos + len(op) :].lstrip().lstrip("+-")
    text: str | None = None
    if ":" in rest:
        to_id, text_part = rest.split(":", 1)
        to_id = to_id.strip()
        text = _non_empty(decode_html_entities(text_part.strip()))
    else:
        to_id = rest.strip()
    if not to_id:
        return None
    src_idx = seq.participant(from_id, None)
    if src_idx is None:
        return None
    dst_idx = seq.participant(to_id, None)
    if dst_idx is None:
        return None
    return src_idx, dst_idx, text, dashed, head


def _div_ceil(a: int, b: int) -> int:
    return -(-a // b)


def _note_geometry(xs: list[int], anchor: NoteAnchor, text_w: int) -> tuple[int, int]:
    if anchor.kind is NoteKind.OVER:
        center = (xs[anchor.a] + xs[anchor.b]) // 2
        w = max(xs[anchor.b] - xs[anchor.a] + 5, text_w + 2 * PAD + 2)
        return max(center - w // 2, 0), w
    if anchor.kind is NoteKind.LEFT:
        w = text_w + 2 * PAD + 2
        return max(xs[anchor.a] - (2 + w - 1), 0), w
    return xs[anchor.a] + 2, text_w + 2 * PAD + 2


def _layout_sequence(seq: SeqDiagram, styles: MermaidStyles, max_width: int | None) -> MermaidArt:
    n = len(seq.labels)
    labels = [_fit_label(label, WRAP_WIDTH) for label in seq.labels]
    box_w = [max(cell_len(label), 1) + 2 * PAD + 2 for label in labels]
    box_h = 3

    def item_text_w(text: str | None) -> int:
        return cell_len(text) if text is not None else 0

    gaps = [max(SEQ_GAP, _div_ceil(box_w[i], 2) + _div_ceil(box_w[i + 1], 2) + 1) for i in range(max(n - 1, 0))]

    reqs: list[tuple[int, int, int]] = []
    for item in seq.items:
        if isinstance(item, SeqMessage):
            tw = item_text_w(item.text)
            if item.src != item.dst:
                lo, hi = min(item.src, item.dst), max(item.src, item.dst)
                reqs.append((lo, hi, max(tw + 2, 4)))
            elif item.src + 1 < n:
                reqs.append((item.src, item.src + 1, 5 + tw + 2))
        elif isinstance(item, SeqNote):
            tw = cell_len(item.text)
            anchor = item.anchor
            if anchor.kind is NoteKind.OVER and anchor.a < anchor.b:
                reqs.append((anchor.a, anchor.b, max(tw - 1, 0)))
            elif anchor.kind is NoteKind.OVER:
                i = anchor.a
                half = _div_ceil(tw + 4, 2) + 2
                if i > 0:
                    reqs.append((i - 1, i, half))
                if i + 1 < n:
                    reqs.append((i, i + 1, half))
            elif anchor.kind is NoteKind.LEFT and anchor.a > 0:
                reqs.append((anchor.a - 1, anchor.a, tw + 7))
            elif anchor.kind is NoteKind.RIGHT and anchor.a + 1 < n:
                reqs.append((anchor.a, anchor.a + 1, tw + 7))
    reqs.sort(key=lambda req: req[1] - req[0])
    for lo, hi, need in reqs:
        cur = sum(gaps[lo:hi])
        if cur < need:
            gaps[hi - 1] += need - cur

    xs = [0] * n
    xs[0] = box_w[0] // 2
    for i in range(1, n):
        xs[i] = xs[i - 1] + gaps[i - 1]

    canvas_w = xs[n - 1] + _div_ceil(box_w[n - 1], 2) + 1
    for item in seq.items:
        if isinstance(item, SeqMessage):
            if item.src == item.dst:
                canvas_w = max(canvas_w, xs[item.src] + 5 + item_text_w(item.text) + 1)
        elif isinstance(item, SeqNote):
            x, w = _note_geometry(xs, item.anchor, cell_len(item.text))
            canvas_w = max(canvas_w, x + w + 1)
        else:
            canvas_w = max(canvas_w, cell_len(item.text) + 4)

    rows: list[int] = []
    y = box_h + 1
    for item in seq.items:
        rows.append(y)
        if isinstance(item, SeqMessage):
            if item.src == item.dst:
                y += 4
            elif item.text is not None:
                y += 3
            else:
                y += 2
        elif isinstance(item, SeqNote):
            y += 4
        else:
            y += 2
    bottom_top = y
    canvas_h = bottom_top + box_h

    if max_width is not None and canvas_w > max_width:
        raise _OversizeError(Oversize.WIDTH)
    if canvas_w * canvas_h > MAX_CANVAS_CELLS:
        raise _OversizeError(Oversize.CELLS)

    canvas = Canvas(canvas_w, canvas_h)
    for i in range(n):
        for by in (0, bottom_top):
            p = Placed(max(xs[i] - box_w[i] // 2, 0), by, box_w[i], box_h, xs[i], by + 1, 0)
            _draw_box(canvas, p, [labels[i]], Shape.RECT)
    for item, r in zip(seq.items, rows, strict=True):
        if isinstance(item, SeqNote):
            x, w = _note_geometry(xs, item.anchor, cell_len(item.text))
            p = Placed(x, r, w, 3, x + w // 2, r + 1, 0)
            _draw_box(canvas, p, [item.text], Shape.RECT)
    for x in xs:
        canvas.junction(x, box_h - 1, D)
        canvas.seg_v(x, box_h, bottom_top - 1)
        canvas.junction(x, bottom_top, U)

    for item, r in zip(seq.items, rows, strict=True):
        if isinstance(item, SeqMessage):
            line_ch = "╌" if item.dashed else "─"
            if item.src == item.dst:
                x = xs[item.src]
                canvas.junction(x, r, R)
                canvas.set(x + 1, r, line_ch, Cls.EDGE)
                canvas.set(x + 2, r, line_ch, Cls.EDGE)
                canvas.set(x + 3, r, "╮", Cls.EDGE)
                canvas.set(x + 3, r + 1, "│", Cls.EDGE)
                canvas.set(x + 1, r + 2, "×" if item.head is SeqHead.CROSS else "◄", Cls.EDGE)
                canvas.set(x + 2, r + 2, line_ch, Cls.EDGE)
                canvas.set(x + 3, r + 2, "╯", Cls.EDGE)
                if item.text is not None:
                    _draw_seq_text(canvas, item.text, x + 5, r + 1, Cls.TEXT)
            else:
                x0, x1 = xs[item.src], xs[item.dst]
                rightward = x1 > x0
                arrow_row = r + 1 if item.text is not None else r
                lo, hi = min(x0, x1), max(x0, x1)
                canvas.junction(x0, arrow_row, R if rightward else L)
                for x in range(lo + 1, hi):
                    canvas.set(x, arrow_row, line_ch, Cls.EDGE)
                arrow_ch = "▶" if rightward else "◄"
                head_ch = "×" if item.head is SeqHead.CROSS else arrow_ch
                head_x = x1 - 1 if rightward else x1 + 1
                canvas.set(head_x, arrow_row, head_ch, Cls.EDGE)
                if item.text is not None:
                    span = hi - lo - 1
                    t = _fit_label(item.text, max(span, 1))
                    tx = lo + 1 + max(span - cell_len(t), 0) // 2
                    _draw_seq_text(canvas, t, tx, r, Cls.TEXT)
        elif isinstance(item, SeqDivider):
            for x in range(canvas_w):
                canvas.set(x, r, "─", Cls.EDGE)
            t = _fit_label(item.text, max(canvas_w - 4, 0))
            _draw_seq_text(canvas, f" {t} ", 2, r, Cls.EDGE_LABEL)

    canvas.finalize_mask()
    return _art_from_canvas(canvas, styles)


def _draw_seq_text(canvas: Canvas, text: str, x: int, y: int, cls: int) -> None:
    cur = x
    for c in text:
        cw = _char_w1(c)
        for k in range(cw):
            if canvas._inside(cur + k, y):
                canvas.mask[canvas.idx(cur + k, y)] = 0
            canvas.set(cur + k, y, c if k == 0 else CONT, cls)
        cur += cw


# ---------------------------------------------------------------------------
# Fallback and entry point
# ---------------------------------------------------------------------------

TOO_WIDE_HINT = "This diagram is too wide to draw here, so the source is shown instead."


def _fallback(src: str, styles: MermaidStyles, max_width: int | None, too_wide: bool) -> MermaidArt:
    header = _first_word(src)
    title = f" mermaid: {header} "
    limit = max(max_width - 4, 8) if max_width is not None else None
    body: list[str] = []
    started = False
    for raw in src.splitlines():
        line = raw.rstrip()
        if not started:
            if not line:
                continue
            started = True
        body.extend(_chunk_line(line, limit))
    content_w = max([cell_len(line) for line in body] + [cell_len(title)])
    inner = content_w + 2

    styled: list[Text] = []
    plain: list[str] = []

    top_fill = "─" * max(inner - cell_len(title), 0)
    top = Text(no_wrap=True)
    top.append("╭", styles.border)
    top.append(title, styles.title)
    top.append(top_fill + "╮", styles.border)
    styled.append(top)
    plain.append("╭" + title + top_fill + "╮")

    for line in body:
        pad = " " * max(content_w - cell_len(line), 0)
        row = Text(no_wrap=True)
        row.append("│ ", styles.border)
        row.append(line, styles.node_text)
        row.append(pad + " │", styles.border)
        styled.append(row)
        plain.append(f"│ {line}{pad} │")

    bottom = "╰" + "─" * inner + "╯"
    styled.append(Text(bottom, style=styles.border, no_wrap=True))
    plain.append(bottom)

    if too_wide:
        hint_style = styles.border + Style(italic=True)
        for chunk in _wrap_words(TOO_WIDE_HINT, max_width):
            styled.append(Text(chunk, style=hint_style, no_wrap=True))
            plain.append(chunk)

    return MermaidArt(styled, plain)


def _chunk_line(line: str, limit: int | None) -> list[str]:
    if limit is None or cell_len(line) <= limit:
        return [line]
    out: list[str] = []
    cur = ""
    cur_w = 0
    for c in line:
        cw = _char_w1(c)
        if cur_w + cw > limit and cur:
            out.append(cur)
            cur = ""
            cur_w = 0
        cur += c
        cur_w += cw
    if cur:
        out.append(cur)
    return out


def _wrap_words(text: str, limit: int | None) -> list[str]:
    if limit is None:
        return [text]
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        if not word:
            continue
        if not cur:
            cur = word
        elif cell_len(cur) + 1 + cell_len(word) <= limit:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return [chunk for line in lines for chunk in _chunk_line(line, limit)]


def _first_word(src: str) -> str:
    words = src.split()
    return words[0] if words else "diagram"


def render(src: str, styles: MermaidStyles, max_width: int | None) -> MermaidArt | None:
    """Render a mermaid source block, or `None` for blank input.

    Diagrams wider than `max_width` (and diagram types this renderer does not
    understand) fall back to the raw source in a framed box.
    """
    if not src.strip():
        return None

    too_wide = False
    try:
        graph = parse_graph(src)
        if graph is not None:
            if graph.groups:
                return _render_grouped(graph, styles, max_width)
            return _layout_flowchart(graph, styles, max_width)
        state = parse_state(src)
        if state is not None:
            return _layout_flowchart(state, styles, max_width)
        class_parsed = parse_class(src)
        if class_parsed is not None:
            return _render_class(class_parsed[0], class_parsed[1], styles, max_width)
        er_parsed = parse_er(src)
        if er_parsed is not None:
            return _render_class(er_parsed[0], er_parsed[1], styles, max_width)
        seq = parse_sequence(src)
        if seq is not None:
            return _layout_sequence(seq, styles, max_width)
    except _OversizeError as exc:
        too_wide = exc.kind is Oversize.WIDTH
    return _fallback(src, styles, max_width, too_wide)
