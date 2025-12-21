from pydantic import BaseModel

from klaude_code.llm.openai_compatible.stream import ReasoningDeltaResult, ReasoningHandlerABC
from klaude_code.protocol import model
from klaude_code.trace import log


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


class ReasoningStreamHandler(ReasoningHandlerABC):
    """Accumulates OpenRouter reasoning details and emits ordered outputs."""

    def __init__(
        self,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id

        self._reasoning_id: str | None = None
        self._accumulated_reasoning: list[str] = []

    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""
        self._response_id = response_id

    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        """Parse OpenRouter's reasoning_details and return ordered stream outputs."""
        reasoning_details = getattr(delta, "reasoning_details", None)
        if not reasoning_details:
            return ReasoningDeltaResult(handled=False, outputs=[])

        outputs: list[str | model.ConversationItem] = []
        for item in reasoning_details:
            try:
                reasoning_detail = ReasoningDetail.model_validate(item)
                if reasoning_detail.text:
                    outputs.append(reasoning_detail.text)
                if reasoning_detail.summary:
                    outputs.append(reasoning_detail.summary)
                outputs.extend(self.on_detail(reasoning_detail))
            except Exception as e:
                log("reasoning_details error", str(e), style="red")

        return ReasoningDeltaResult(handled=True, outputs=outputs)

    def on_detail(self, detail: ReasoningDetail) -> list[model.ConversationItem]:
        """Process a single reasoning detail and return streamable items."""
        items: list[model.ConversationItem] = []

        if detail.type == "reasoning.encrypted":
            self._reasoning_id = detail.id
            # Flush accumulated text before encrypted content
            items.extend(self._flush_text())
            if encrypted_item := self._build_encrypted_item(detail.data, detail):
                items.append(encrypted_item)
            return items

        if detail.type in ("reasoning.text", "reasoning.summary"):
            self._reasoning_id = detail.id
            # Accumulate text
            text = detail.text if detail.type == "reasoning.text" else detail.summary
            if text:
                self._accumulated_reasoning.append(text)
            # Flush on signature (encrypted content)
            if detail.signature:
                items.extend(self._flush_text())
                if encrypted_item := self._build_encrypted_item(detail.signature, detail):
                    items.append(encrypted_item)

        return items

    def flush(self) -> list[model.ConversationItem]:
        """Flush buffered reasoning text on finalize."""
        return self._flush_text()

    def _flush_text(self) -> list[model.ConversationItem]:
        """Flush accumulated reasoning text as a single item."""
        if not self._accumulated_reasoning:
            return []
        item = self._build_text_item("".join(self._accumulated_reasoning))
        self._accumulated_reasoning = []
        return [item]

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
