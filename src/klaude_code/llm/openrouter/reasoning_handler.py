from enum import Enum

from pydantic import BaseModel

from klaude_code.protocol import model


class ReasoningDetail(BaseModel):
    """OpenRouter's https://openrouter.ai/docs/use-cases/reasoning-tokens#reasoning_details-array-structure"""

    type: str
    format: str
    index: int
    id: str | None = None
    data: str | None = None  # OpenAI's encrypted content
    summary: str | None = None
    text: str | None = None
    signature: str | None = None  # Claude's signature


class ReasoningMode(str, Enum):
    COMPLETE_CHUNK = "complete_chunk"
    GPT5_SECTIONS = "gpt5_sections"
    ACCUMULATE = "accumulate"


class ReasoningStreamHandler:
    """Encapsulates reasoning stream handling across different model behaviors."""

    def __init__(
        self,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id

        self._reasoning_id: str | None = None
        self._accumulated_reasoning: list[str] = []
        self._gpt5_line_buffer: str = ""
        self._gpt5_section_lines: list[str] = []

    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""

        self._response_id = response_id

    def on_detail(self, detail: ReasoningDetail) -> list[model.ConversationItem]:
        """Process a single reasoning detail and return streamable items."""

        items: list[model.ConversationItem] = []

        if detail.type == "reasoning.encrypted":
            self._reasoning_id = detail.id
            if encrypted_item := self._build_encrypted_item(detail.data, detail):
                items.append(encrypted_item)
            return items

        if detail.type in ("reasoning.text", "reasoning.summary"):
            self._reasoning_id = detail.id
            if encrypted_item := self._build_encrypted_item(detail.signature, detail):
                items.append(encrypted_item)
            text = detail.text if detail.type == "reasoning.text" else detail.summary
            if text:
                items.extend(self._handle_text(text))

        return items

    def flush(self) -> list[model.ConversationItem]:
        """Flush buffered reasoning text and encrypted payloads."""

        items: list[model.ConversationItem] = []
        mode = self._resolve_mode()

        if mode is ReasoningMode.GPT5_SECTIONS:
            for section in self._drain_gpt5_sections():
                items.append(self._build_text_item(section))
        elif self._accumulated_reasoning and mode is ReasoningMode.ACCUMULATE:
            items.append(self._build_text_item("".join(self._accumulated_reasoning)))
            self._accumulated_reasoning = []

        return items

    def _handle_text(self, text: str) -> list[model.ReasoningTextItem]:
        mode = self._resolve_mode()
        if mode is ReasoningMode.COMPLETE_CHUNK:
            return [self._build_text_item(text)]
        if mode is ReasoningMode.GPT5_SECTIONS:
            sections = self._process_gpt5_text(text)
            return [self._build_text_item(section) for section in sections]
        self._accumulated_reasoning.append(text)
        return []

    def _build_text_item(self, content: str) -> model.ReasoningTextItem:
        return model.ReasoningTextItem(
            id=self._reasoning_id,
            content=content,
            response_id=self._response_id,
            model=self._param_model,
        )

    def _build_encrypted_item(
        self,
        content: str | None,
        detail: ReasoningDetail,
    ) -> model.ReasoningEncryptedItem | None:
        if not content:
            return None
        return model.ReasoningEncryptedItem(
            id=detail.id,
            encrypted_content=content,
            format=detail.format,
            response_id=self._response_id,
            model=self._param_model,
        )

    def _process_gpt5_text(self, text: str) -> list[str]:
        emitted_sections: list[str] = []
        self._gpt5_line_buffer += text
        while True:
            newline_index = self._gpt5_line_buffer.find("\n")
            if newline_index == -1:
                break
            line = self._gpt5_line_buffer[:newline_index]
            self._gpt5_line_buffer = self._gpt5_line_buffer[newline_index + 1 :]
            remainder = line
            while True:
                split_result = self._split_gpt5_title_line(remainder)
                if split_result is None:
                    break
                prefix_segment, title_segment, remainder = split_result
                if prefix_segment:
                    if not self._gpt5_section_lines:
                        self._gpt5_section_lines = []
                    self._gpt5_section_lines.append(f"{prefix_segment}\n")
                if self._gpt5_section_lines:
                    emitted_sections.append("".join(self._gpt5_section_lines))
                self._gpt5_section_lines = [f"{title_segment}  \n"]  # Add two spaces for markdown line break
            if remainder:
                if not self._gpt5_section_lines:
                    self._gpt5_section_lines = []
                self._gpt5_section_lines.append(f"{remainder}\n")
        return emitted_sections

    def _drain_gpt5_sections(self) -> list[str]:
        sections: list[str] = []
        if self._gpt5_line_buffer:
            if not self._gpt5_section_lines:
                self._gpt5_section_lines = [self._gpt5_line_buffer]
            else:
                self._gpt5_section_lines.append(self._gpt5_line_buffer)
            self._gpt5_line_buffer = ""
        if self._gpt5_section_lines:
            sections.append("".join(self._gpt5_section_lines))
            self._gpt5_section_lines = []
        return sections

    def _is_gpt5(self) -> bool:
        return "gpt-5" in self._param_model.lower()

    def _is_complete_chunk_reasoning_model(self) -> bool:
        """Whether the current model emits reasoning in complete chunks (e.g. Gemini)."""

        return self._param_model.startswith("google/gemini")

    def _resolve_mode(self) -> ReasoningMode:
        if self._is_complete_chunk_reasoning_model():
            return ReasoningMode.COMPLETE_CHUNK
        if self._is_gpt5():
            return ReasoningMode.GPT5_SECTIONS
        return ReasoningMode.ACCUMULATE

    def _is_gpt5_title_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        return stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") >= 2

    def _split_gpt5_title_line(self, line: str) -> tuple[str | None, str, str] | None:
        if not line:
            return None
        search_start = 0
        while True:
            opening_index = line.find("**", search_start)
            if opening_index == -1:
                return None
            closing_index = line.find("**", opening_index + 2)
            if closing_index == -1:
                return None
            title_candidate = line[opening_index : closing_index + 2]
            stripped_title = title_candidate.strip()
            if self._is_gpt5_title_line(stripped_title):
                # Treat as a GPT-5 title only when everything after the
                # bold segment is either whitespace or starts a new bold
                # title. This prevents inline bold like `**xxx**yyyy`
                # from being misclassified as a section title while
                # preserving support for consecutive titles in one line.
                after = line[closing_index + 2 :]
                if after.strip() and not after.lstrip().startswith("**"):
                    search_start = closing_index + 2
                    continue
                prefix_segment = line[:opening_index]
                remainder_segment = after
                return (
                    prefix_segment if prefix_segment else None,
                    stripped_title,
                    remainder_segment,
                )
            search_start = closing_index + 2
