"""AWS Bedrock LLM client using Anthropic SDK."""

import json
from collections.abc import AsyncGenerator
from typing import override

import anthropic
import httpx
from anthropic import APIError

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.anthropic.client import build_payload, parse_anthropic_stream
from klaude_code.llm.client import LLMClientABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_stream_items
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param, message


@register(llm_param.LLMClientProtocol.BEDROCK)
class BedrockClient(LLMClientABC):
    """LLM client for AWS Bedrock using Anthropic SDK."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self.client = anthropic.AsyncAnthropicBedrock(
            aws_access_key=config.aws_access_key,
            aws_secret_key=config.aws_secret_key,
            aws_region=config.aws_region,
            aws_session_token=config.aws_session_token,
            aws_profile=config.aws_profile,
            timeout=httpx.Timeout(LLM_HTTP_TIMEOUT_TOTAL, connect=LLM_HTTP_TIMEOUT_CONNECT, read=LLM_HTTP_TIMEOUT_READ),
        )

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> AsyncGenerator[message.LLMStreamItem]:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        stream = self.client.beta.messages.create(**payload)

        try:
            async for item in parse_anthropic_stream(stream, param, metadata_tracker):
                yield item
        except (APIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            for item in error_stream_items(metadata_tracker, error=error_message):
                yield item
