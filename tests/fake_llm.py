"""Scripted offline models shared by runtime and transport tests."""

from __future__ import annotations

import asyncio

from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage


class ScriptedLLMStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem], *, delay_s: float = 0.0) -> None:
        self._items = items
        self._delay_s = delay_s
        self._partial_parts: list[message.Part] = []
        self._response_id: str | None = None
        self._final_message: message.AssistantMessage | None = None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self._items:
            if self._delay_s > 0:
                await asyncio.sleep(self._delay_s)
            if isinstance(item, message.ThinkingTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.ThinkingTextPart(text=item.content))
            elif isinstance(item, message.AssistantTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.TextPart(text=item.content))
            elif isinstance(item, message.AssistantMessage):
                self._final_message = item
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._final_message is not None:
            return self._final_message
        if not self._partial_parts:
            return None
        return message.AssistantMessage(
            parts=list(self._partial_parts),
            response_id=self._response_id,
            stop_reason="aborted",
        )


class FakeLLMClient(LLMClientABC):
    def __init__(self) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-model",
            )
        )
        self._responses: list[tuple[list[message.LLMStreamItem], float]] = []
        self.call_count = 0

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls()

    def enqueue(self, *items: message.LLMStreamItem, delay_s: float = 0.0) -> None:
        self._responses.append((list(items), delay_s))

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no queued response")
        items, delay_s = self._responses.pop(0)
        return ScriptedLLMStream(items, delay_s=delay_s)


def usage(
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    cached_tokens: int = 0,
) -> Usage:
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        context_size=input_tokens + output_tokens,
        context_limit=200_000,
        model_name="fake-model",
        provider="test",
    )
