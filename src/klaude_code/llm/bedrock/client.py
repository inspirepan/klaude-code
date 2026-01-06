"""AWS Bedrock LLM client using Anthropic SDK."""

import json
from typing import override

import anthropic
import httpx
from anthropic import APIError

from klaude_code.const import LLM_HTTP_TIMEOUT_CONNECT, LLM_HTTP_TIMEOUT_READ, LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.anthropic.client import AnthropicLLMStream, build_payload
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import llm_param


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
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())

        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        payload = build_payload(param)

        log_debug(
            json.dumps(payload, ensure_ascii=False, default=str),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        try:
            stream = self.client.beta.messages.create(**payload)
            return AnthropicLLMStream(stream, param=param, metadata_tracker=metadata_tracker)
        except (APIError, httpx.HTTPError) as e:
            error_message = f"{e.__class__.__name__} {e!s}"
            return error_llm_stream(metadata_tracker, error=error_message)
