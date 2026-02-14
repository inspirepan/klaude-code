from klaude_code.llm.openai_compatible.stream import ReasoningDeltaResult, ReasoningDetail, ReasoningHandlerABC
from klaude_code.log import log
from klaude_code.protocol import message


class ReasoningStreamHandler(ReasoningHandlerABC):
    """Accumulates OpenRouter reasoning details and emits ordered outputs.

    Unlike DefaultReasoningHandler, this handler is OpenRouter-specific:
    it handles Claude's inline signature on reasoning.text items and
    OpenAI's reasoning.encrypted items via separate code paths.
    """

    def __init__(
        self,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id

        self._reasoning_id: str | None = None

    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""
        self._response_id = response_id

    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        """Parse OpenRouter's reasoning_details and return ordered stream outputs."""
        reasoning_details = getattr(delta, "reasoning_details", None)
        if not reasoning_details:
            return ReasoningDeltaResult(handled=False, outputs=[])

        outputs: list[str | message.Part] = []
        for item in reasoning_details:
            try:
                detail = ReasoningDetail.model_validate(item)
                if detail.text:
                    outputs.append(detail.text)
                if detail.summary:
                    outputs.append(detail.summary)
                outputs.extend(self._on_detail(detail))
            except Exception as e:
                log("reasoning_details error", str(e), style="red")

        return ReasoningDeltaResult(handled=True, outputs=outputs)

    def _on_detail(self, detail: ReasoningDetail) -> list[message.Part]:
        """Process a single reasoning detail and return streamable parts."""
        items: list[message.Part] = []

        if detail.type == "reasoning.encrypted":
            self._reasoning_id = detail.id
            if signature_part := self._build_signature_part(detail.data, detail):
                items.append(signature_part)
            return items

        if detail.type in ("reasoning.text", "reasoning.summary"):
            self._reasoning_id = detail.id
            # Signature (Anthropic-style) can arrive alongside text/summary.
            if detail.signature and (signature_part := self._build_signature_part(detail.signature, detail)):
                items.append(signature_part)

        return items

    def flush(self) -> list[message.Part]:
        return []

    def _build_signature_part(
        self,
        content: str | None,
        detail: ReasoningDetail,
    ) -> message.ThinkingSignaturePart | None:
        if not content:
            return None
        return message.ThinkingSignaturePart(
            id=detail.id,
            signature=content,
            format=detail.format,
            model_id=self._param_model,
        )
