import ast
from pathlib import Path
from typing import Iterable

from klaude_code.llm.openrouter.client import ReasoningDetail, ReasoningStreamHandler
from klaude_code.protocol import model


def _load_reasoning_details() -> list[ReasoningDetail]:
    log_path = Path(__file__).resolve().parent / "gpt-5-reasoning-input.log"
    details: list[ReasoningDetail] = []
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if "reasoning_details=" not in stripped:
            continue
        start_index = stripped.index("reasoning_details=")
        start_bracket = stripped.index("[", start_index)
        end_bracket = stripped.rfind("]")
        parsed = ast.literal_eval(stripped[start_bracket : end_bracket + 1])
        if not parsed:
            continue
        detail = ReasoningDetail.model_validate(parsed[0])
        details.append(detail)
    return details


def _collect_reasoning_text(items: Iterable[model.ConversationItem]) -> list[str]:
    texts: list[str] = []
    for item in items:
        if isinstance(item, model.ReasoningTextItem):
            texts.append(item.content)
    return texts


def test_gpt5_reasoning_sections_emit_on_title_boundaries() -> None:
    details = _load_reasoning_details()
    handler = ReasoningStreamHandler(param_model="gpt-5.1", response_id="resp-1")

    streamed_sections: list[str] = []
    for detail in details:
        streamed_sections.extend(_collect_reasoning_text(handler.on_detail(detail)))

    flushed_sections = _collect_reasoning_text(handler.flush())

    assert len(streamed_sections) == 4
    assert len(flushed_sections) == 1

    sections = streamed_sections + flushed_sections
    expected_titles = [
        "Designing the class",
        "Analyzing current configurations",
        "Clarifying GPT-5 paths",
        "Designing with delta content",
        "Proposing the ReasoningStreamHandler class",
    ]

    assert len(sections) == len(expected_titles)

    for section, title in zip(sections, expected_titles):
        assert section.startswith(f"**{title}**")

    for idx in range(len(expected_titles) - 1):
        next_title = f"**{expected_titles[idx + 1]}**"
        assert next_title not in sections[idx]


def test_gpt5_inline_title_split() -> None:
    handler = ReasoningStreamHandler(param_model="gpt-5.1", response_id="resp-inline")
    details = [
        ReasoningDetail(
            type="reasoning.summary",
            summary="**First Section**\nbody line\n",
            format="openai-responses-v1",
            index=0,
        ),
        ReasoningDetail(
            type="reasoning.summary",
            summary="closing line before new section**Second Section**\nbody line after split\n",
            format="openai-responses-v1",
            index=1,
        ),
    ]

    sections: list[str] = []
    for detail in details:
        sections.extend(_collect_reasoning_text(handler.on_detail(detail)))

    sections.extend(_collect_reasoning_text(handler.flush()))

    assert len(sections) == 2
    assert sections[0].startswith("**First Section**  \n")
    assert sections[0].endswith("closing line before new section\n")
    assert sections[1].startswith("**Second Section**  \n")
    assert sections[1].endswith("body line after split\n")


def test_gpt5_consecutive_titles_within_line() -> None:
    handler = ReasoningStreamHandler(param_model="gpt-5.1", response_id="resp-consecutive")
    chunks = [
        "**Title One",
        "****Title Two",
        "****Title Three**\n",
    ]
    sections: list[str] = []

    for idx, chunk in enumerate(chunks):
        detail = ReasoningDetail(
            type="reasoning.summary",
            summary=chunk,
            format="openai-responses-v1",
            index=idx,
        )
        sections.extend(_collect_reasoning_text(handler.on_detail(detail)))

    sections.extend(_collect_reasoning_text(handler.flush()))

    assert len(sections) == 3
    assert sections[0].strip() == "**Title One**"
    assert sections[1].strip() == "**Title Two**"
    assert sections[2].strip() == "**Title Three**"
