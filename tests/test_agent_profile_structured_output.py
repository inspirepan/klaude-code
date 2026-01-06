from __future__ import annotations

from collections.abc import AsyncGenerator

from klaude_code.core.agent_profile import STRUCTURED_OUTPUT_PROMPT_FOR_SUB_AGENT, DefaultModelProfileProvider
from klaude_code.llm import LLMClientABC
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import llm_param, message, tools


class DummyLLMStream(LLMStreamABC):
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        if False:  # pragma: no cover
            yield message.AssistantMessage(parts=[], response_id=None)

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class DummyLLMClient(LLMClientABC):
    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config)

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        return DummyLLMStream()


def test_default_profile_provider_injects_report_back_on_output_schema() -> None:
    provider = DefaultModelProfileProvider()
    client = DummyLLMClient(
        llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.OPENAI, model_id="gpt-5.2-codex")
    )

    schema = {
        "type": "OBJECT",
        "properties": {"foo": {"type": "STRING"}},
        "required": ["foo"],
    }

    profile = provider.build_profile(client, output_schema=schema)
    assert profile.system_prompt is not None
    assert profile.system_prompt.endswith(STRUCTURED_OUTPUT_PROMPT_FOR_SUB_AGENT)

    assert profile.tools
    report_back = profile.tools[-1]
    assert report_back.name == tools.REPORT_BACK
    assert report_back.parameters["type"] == "object"
    assert report_back.parameters["properties"]["foo"]["type"] == "string"
