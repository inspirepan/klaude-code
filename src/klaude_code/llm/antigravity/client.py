"""Antigravity LLM client using Cloud Code Assist API."""

import asyncio
import json
import re
from base64 import b64encode
from collections.abc import AsyncGenerator
from typing import TypedDict, override
from uuid import uuid4

import httpx

from klaude_code.auth.antigravity import AntigravityOAuth, AntigravityTokenManager
from klaude_code.llm.antigravity.input import Content, Tool, convert_history_to_contents, convert_tool_schema
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.image import save_assistant_image
from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.llm.registry import register
from klaude_code.llm.stream_parts import (
    append_text_part,
    append_thinking_text_part,
    build_partial_message,
    build_partial_parts,
)
from klaude_code.llm.usage import MetadataTracker, error_llm_stream
from klaude_code.log import DebugType, debug_json, log_debug
from klaude_code.protocol import llm_param, message, model

# Unified format for Google thought signatures
GOOGLE_THOUGHT_SIGNATURE_FORMAT = "google"

# Cloud Code Assist API endpoint
DEFAULT_ENDPOINT = "https://cloudcode-pa.googleapis.com"

# Antigravity headers
ANTIGRAVITY_HEADERS = {
    "User-Agent": "antigravity/1.11.5 darwin/arm64",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": json.dumps(
        {
            "ideType": "IDE_UNSPECIFIED",
            "platform": "PLATFORM_UNSPECIFIED",
            "pluginType": "GEMINI",
        }
    ),
}

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY_MS = 1000


class ThinkingConfig(TypedDict, total=False):
    includeThoughts: bool
    thinkingBudget: int
    thinkingLevel: str


class GenerationConfig(TypedDict, total=False):
    maxOutputTokens: int
    temperature: float
    thinkingConfig: ThinkingConfig | None


class ToolConfig(TypedDict, total=False):
    functionCallingConfig: dict[str, str]


class SystemInstruction(TypedDict, total=False):
    role: str
    parts: list[dict[str, str]]


class RequestBody(TypedDict, total=False):
    contents: list[Content]
    systemInstruction: SystemInstruction
    generationConfig: GenerationConfig
    tools: list[Tool]
    toolConfig: ToolConfig


class CloudCodeAssistRequest(TypedDict, total=False):
    project: str
    model: str
    request: RequestBody
    requestType: str
    userAgent: str
    requestId: str


def _convert_thinking_level(reasoning_effort: str | None) -> str | None:
    """Convert reasoning_effort to Gemini ThinkingLevel."""
    if reasoning_effort is None:
        return None
    mapping: dict[str, str] = {
        "xhigh": "HIGH",
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
        "minimal": "MINIMAL",
        "none": "MINIMAL",
    }
    return mapping.get(reasoning_effort)


def _extract_retry_delay(error_text: str) -> int | None:
    """Extract retry delay from error response in milliseconds."""
    # Pattern: "Your quota will reset after 39s" or "18h31m10s"
    match = re.search(r"reset after (?:(\d+)h)?(?:(\d+)m)?(\d+(?:\.\d+)?)s", error_text, re.IGNORECASE)
    if match:
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        seconds = float(match.group(3))
        total_ms = int(((hours * 60 + minutes) * 60 + seconds) * 1000)
        if total_ms > 0:
            return total_ms + 1000  # Add 1s buffer

    # Pattern: "Please retry in X[ms|s]"
    match = re.search(r"Please retry in ([0-9.]+)(ms|s)", error_text, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        if match.group(2).lower() == "ms":
            return int(value) + 1000
        return int(value * 1000) + 1000

    # Pattern: "retryDelay": "34.074824224s"
    match = re.search(r'"retryDelay":\s*"([0-9.]+)(ms|s)"', error_text, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        if match.group(2).lower() == "ms":
            return int(value) + 1000
        return int(value * 1000) + 1000

    return None


def _is_retryable_error(status: int, error_text: str) -> bool:
    """Check if an error is retryable.

    Note: 429 is NOT retryable - fail immediately to let caller rotate accounts.
    """
    if status in (500, 502, 503, 504):
        return True
    # Exclude rate limit patterns - let caller handle account rotation
    if status == 429:
        return False
    return bool(re.search(r"overloaded|service.?unavailable", error_text, re.IGNORECASE))


def _map_finish_reason(reason: str) -> model.StopReason | None:
    """Map finish reason string to StopReason."""
    mapping: dict[str, model.StopReason] = {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "error",
        "RECITATION": "error",
        "OTHER": "error",
    }
    return mapping.get(reason.upper())


def _encode_thought_signature(sig: bytes | str | None) -> str | None:
    """Encode thought signature to base64 string."""
    if sig is None:
        return None
    if isinstance(sig, bytes):
        return b64encode(sig).decode("ascii")
    return sig


def _build_request(
    param: llm_param.LLMCallParameter,
    contents: list[Content],
    project_id: str,
) -> CloudCodeAssistRequest:
    """Build Cloud Code Assist API request."""
    request: RequestBody = {"contents": contents}

    # System instruction from param.system
    if param.system:
        request["systemInstruction"] = {
            "role": "user",
            "parts": [{"text": param.system}],
        }

    # Generation config
    generation_config: GenerationConfig = {}
    if param.temperature is not None:
        generation_config["temperature"] = param.temperature
    if param.max_tokens is not None:
        generation_config["maxOutputTokens"] = param.max_tokens

    # Thinking config
    thinking_config: ThinkingConfig | None = None
    if param.thinking:
        thinking_config = {"includeThoughts": True}
        if param.thinking.budget_tokens:
            thinking_config["thinkingBudget"] = param.thinking.budget_tokens
        if param.thinking.reasoning_effort:
            level = _convert_thinking_level(param.thinking.reasoning_effort)
            if level:
                thinking_config["thinkingLevel"] = level
    generation_config["thinkingConfig"] = thinking_config

    if generation_config:
        request["generationConfig"] = generation_config

    # Tools
    tools = convert_tool_schema(param.tools)
    if tools:
        request["tools"] = tools
        request["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

    return CloudCodeAssistRequest(
        project=project_id,
        model=str(param.model_id),
        request=request,
        requestType="agent",
        userAgent="antigravity",
        requestId=f"agent-{uuid4().hex[:16]}",
    )


class AntigravityStreamStateManager:
    """Manages streaming state for Antigravity LLM responses."""

    def __init__(self, param_model: str) -> None:
        self.param_model = param_model
        self.assistant_parts: list[message.Part] = []
        self.response_id: str | None = None
        self.stop_reason: model.StopReason | None = None

    def append_thinking_text(self, text: str) -> None:
        append_thinking_text_part(self.assistant_parts, text, model_id=self.param_model)

    def append_text(self, text: str) -> None:
        append_text_part(self.assistant_parts, text)

    def append_thinking_signature(self, signature: str) -> None:
        self.assistant_parts.append(
            message.ThinkingSignaturePart(
                signature=signature,
                model_id=self.param_model,
                format=GOOGLE_THOUGHT_SIGNATURE_FORMAT,
            )
        )

    def append_image(self, image_part: message.ImageFilePart) -> None:
        self.assistant_parts.append(image_part)

    def append_tool_call(self, call_id: str, name: str, arguments_json: str) -> None:
        self.assistant_parts.append(
            message.ToolCallPart(
                call_id=call_id,
                tool_name=name,
                arguments_json=arguments_json,
            )
        )

    def get_partial_parts(self) -> list[message.Part]:
        return build_partial_parts(self.assistant_parts)

    def get_partial_message(self) -> message.AssistantMessage | None:
        return build_partial_message(self.assistant_parts, response_id=self.response_id)


async def _parse_sse_stream(
    response: httpx.Response,
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    state: AntigravityStreamStateManager,
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse SSE stream from Cloud Code Assist API."""
    tool_call_counter = 0
    started_tool_calls: dict[str, tuple[str, str | None]] = {}  # call_id -> (name, thought_signature)
    completed_tool_items: set[str] = set()
    image_index = 0

    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue

        json_str = line[5:].strip()
        if not json_str:
            continue

        try:
            chunk = json.loads(json_str)
        except json.JSONDecodeError:
            continue

        response_data = chunk.get("response")
        if not response_data:
            continue

        if state.response_id is None:
            state.response_id = response_data.get("responseId") or uuid4().hex

        # Process candidates
        candidates = response_data.get("candidates", [])
        candidate0 = candidates[0] if candidates else None
        if not candidate0:
            continue

        finish_reason = candidate0.get("finishReason")
        if finish_reason:
            state.stop_reason = _map_finish_reason(finish_reason)

        content = candidate0.get("content", {})
        content_parts = content.get("parts", [])

        for part in content_parts:
            log_debug(debug_json(part), style="blue", debug_type=DebugType.LLM_STREAM)
            # Handle text parts and thought signatures
            text = part.get("text")
            thought_signature = part.get("thoughtSignature")
            is_thinking = part.get("thought") is True

            if text:
                metadata_tracker.record_token()
                if is_thinking:
                    state.append_thinking_text(text)
                    yield message.ThinkingTextDelta(content=text, response_id=state.response_id)
                else:
                    state.append_text(text)
                    yield message.AssistantTextDelta(content=text, response_id=state.response_id)

            # Handle thought signature (may come with empty text, but not for function calls)
            if thought_signature and not part.get("functionCall"):
                encoded_sig = _encode_thought_signature(thought_signature)
                if encoded_sig:
                    state.append_thinking_signature(encoded_sig)

            # Handle inline_data (image generation)
            inline_data = part.get("inlineData")
            if inline_data and inline_data.get("data"):
                if part.get("thought") is True:
                    continue  # Skip thought images
                mime_type = inline_data.get("mimeType", "image/png")
                data = inline_data["data"]
                data_url = f"data:{mime_type};base64,{data}"
                try:
                    image_part = save_assistant_image(
                        data_url=data_url,
                        session_id=param.session_id,
                        response_id=state.response_id,
                        image_index=image_index,
                    )
                    image_index += 1
                    state.append_image(image_part)
                    yield message.AssistantImageDelta(
                        response_id=state.response_id,
                        file_path=image_part.file_path,
                    )
                except ValueError:
                    pass

            # Handle function calls
            function_call = part.get("functionCall")
            if function_call:
                metadata_tracker.record_token()
                call_id = function_call.get("id") or f"call_{uuid4().hex[:8]}_{tool_call_counter}"
                tool_call_counter += 1
                name = function_call.get("name", "")
                thought_signature = part.get("thoughtSignature")

                if call_id not in started_tool_calls:
                    started_tool_calls[call_id] = (name, thought_signature)
                    yield message.ToolCallStartDelta(response_id=state.response_id, call_id=call_id, name=name)

                args = function_call.get("args")
                if args is not None and call_id not in completed_tool_items:
                    state.append_tool_call(call_id, name, json.dumps(args, ensure_ascii=False))
                    if thought_signature:
                        encoded_sig = _encode_thought_signature(thought_signature)
                        if encoded_sig:
                            state.append_thinking_signature(encoded_sig)
                    completed_tool_items.add(call_id)

        # Process usage metadata
        usage_metadata = response_data.get("usageMetadata")
        if usage_metadata:
            prompt_tokens = usage_metadata.get("promptTokenCount", 0)
            cached_tokens = usage_metadata.get("cachedContentTokenCount", 0)
            candidates_tokens = usage_metadata.get("candidatesTokenCount", 0)
            thoughts_tokens = usage_metadata.get("thoughtsTokenCount", 0)
            total_tokens = usage_metadata.get("totalTokenCount") or (
                prompt_tokens + candidates_tokens + thoughts_tokens
            )

            usage = model.Usage(
                input_tokens=prompt_tokens,
                cached_tokens=cached_tokens,
                output_tokens=candidates_tokens + thoughts_tokens,
                reasoning_tokens=thoughts_tokens,
                context_size=total_tokens,
                context_limit=param.context_limit,
                max_tokens=param.max_tokens,
            )
            metadata_tracker.set_usage(usage)

    # Finalize
    metadata_tracker.set_model_name(str(param.model_id))
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    yield message.AssistantMessage(
        parts=state.assistant_parts,
        response_id=state.response_id,
        usage=metadata,
        stop_reason=state.stop_reason,
    )


class AntigravityLLMStream(LLMStreamABC):
    """LLMStream implementation for Antigravity client."""

    def __init__(
        self,
        response: httpx.Response,
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
        state: AntigravityStreamStateManager,
    ) -> None:
        self._response = response
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._state = state
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        try:
            async for item in _parse_sse_stream(
                self._response,
                param=self._param,
                metadata_tracker=self._metadata_tracker,
                state=self._state,
            ):
                if isinstance(item, message.AssistantMessage):
                    self._completed = True
                yield item
        except httpx.HTTPError as e:
            yield message.StreamErrorItem(error=f"HTTPError: {e}")
            self._metadata_tracker.set_response_id(self._state.response_id)
            yield message.AssistantMessage(
                parts=self._state.get_partial_parts(),
                response_id=self._state.response_id,
                usage=self._metadata_tracker.finalize(),
                stop_reason="error",
            )

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._completed:
            return None
        return self._state.get_partial_message()


@register(llm_param.LLMClientProtocol.ANTIGRAVITY)
class AntigravityClient(LLMClientABC):
    """Antigravity LLM client using Cloud Code Assist API."""

    def __init__(self, config: llm_param.LLMConfigParameter):
        super().__init__(config)
        self._token_manager = AntigravityTokenManager()
        self._oauth = AntigravityOAuth(self._token_manager)
        self._endpoint = config.base_url or DEFAULT_ENDPOINT
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        return self._http_client

    def _get_credentials(self) -> tuple[str, str]:
        """Get access token and project ID, refreshing if needed."""
        return self._oauth.ensure_valid_token()

    @classmethod
    @override
    def create(cls, config: llm_param.LLMConfigParameter) -> "LLMClientABC":
        return cls(config)

    @override
    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        param = apply_config_defaults(param, self.get_llm_config())
        metadata_tracker = MetadataTracker(cost_config=self.get_llm_config().cost)

        # Get credentials
        try:
            access_token, project_id = self._get_credentials()
        except Exception as e:
            return error_llm_stream(metadata_tracker, error=str(e))

        # Convert messages
        contents = convert_history_to_contents(param.input, model_name=str(param.model_id))
        request_body = _build_request(param, contents, project_id)

        log_debug(
            debug_json(request_body),
            style="yellow",
            debug_type=DebugType.LLM_PAYLOAD,
        )

        # Make request with retry logic
        url = f"{self._endpoint}/v1internal:streamGenerateContent?alt=sse"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **ANTIGRAVITY_HEADERS,
        }

        client = await self._get_http_client()
        last_error: str | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json=request_body,
                )

                if response.status_code == 200:
                    state = AntigravityStreamStateManager(param_model=str(param.model_id))
                    return AntigravityLLMStream(
                        response,
                        param=param,
                        metadata_tracker=metadata_tracker,
                        state=state,
                    )

                error_text = response.text
                last_error = f"Cloud Code Assist API error ({response.status_code}): {error_text}"

                # Check if retryable
                if attempt < MAX_RETRIES and _is_retryable_error(response.status_code, error_text):
                    delay_ms = _extract_retry_delay(error_text) or (BASE_DELAY_MS * (2**attempt))
                    await asyncio.sleep(delay_ms / 1000)
                    # Refresh token in case it expired
                    access_token, project_id = self._get_credentials()
                    headers["Authorization"] = f"Bearer {access_token}"
                    continue

                break

            except httpx.HTTPError as e:
                last_error = f"HTTPError: {e}"
                if attempt < MAX_RETRIES:
                    delay_ms = BASE_DELAY_MS * (2**attempt)
                    await asyncio.sleep(delay_ms / 1000)
                    continue
                break

        return error_llm_stream(metadata_tracker, error=last_error or "Request failed")
