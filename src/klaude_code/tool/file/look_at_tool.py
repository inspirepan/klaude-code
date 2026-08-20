from __future__ import annotations

import asyncio
import io
from base64 import b64encode
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from klaude_code.config.config import Config, ModelConfigCandidate
from klaude_code.config.loader import load_config
from klaude_code.const import LOOK_AT_MAX_TOKENS, LOOK_AT_TIMEOUT_SEC, READ_MAX_IMAGE_BYTES
from klaude_code.llm.image import detect_mime_type_from_bytes, freeze_image_to_file_for_history
from klaude_code.llm.registry import create_llm_client
from klaude_code.log import log_debug
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import ImageUIExtra
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.file._read_core import _image_mime_type, _is_supported_image_file, _session_images_dir
from klaude_code.tool.file._utils import file_exists, is_directory
from klaude_code.workspace import resolve_workspace_path

_PROMPT_TEMPLATE = "Fully describe this image, then answer the following question:\n\n{question}"


def _error(text: str) -> message.ToolResultMessage:
    return message.ToolResultMessage(status="error", output_text=f"<tool_use_error>{text}</tool_use_error>")


def _resolve_vision_candidate(config: Config) -> ModelConfigCandidate | None:
    """Pick the first available fast-model candidate that accepts image input."""
    for candidate in config.iter_model_config_candidates(config.fast_model):
        if candidate.llm_config.supports_vision:
            return candidate
    return None


def _crop_region_to_png(
    image_bytes: bytes, region: list[int]
) -> tuple[bytes, tuple[int, int, int, int], tuple[int, int]]:
    """Crop the original image to `region`, clamped to bounds. Returns PNG bytes."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        x1, y1, x2, y2 = region
        x1 = max(0, min(x1, width))
        x2 = max(0, min(x2, width))
        y1 = max(0, min(y1, height))
        y2 = max(0, min(y2, height))
        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                f"region [{region[0]}, {region[1]}, {region[2]}, {region[3]}] is empty after clamping to image bounds {width}x{height}"
            )
        cropped = img.crop((x1, y1, x2, y2))
        if cropped.mode not in ("RGB", "RGBA", "L"):
            cropped = cropped.convert("RGBA")
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG")
        return buffer.getvalue(), (x1, y1, x2, y2), (width, height)


async def _ask_vision_model(
    candidate: ModelConfigCandidate,
    image_part: message.ImageFilePart,
    question: str,
) -> str:
    # Client construction may block on network/tokenizer setup; keep it off the loop.
    client = await asyncio.to_thread(create_llm_client, candidate.llm_config)
    call_param = llm_param.LLMCallParameter(
        input=[
            message.UserMessage(parts=[message.TextPart(text=_PROMPT_TEMPLATE.format(question=question)), image_part])
        ],
        session_id=None,
    )
    call_param.max_tokens = LOOK_AT_MAX_TOKENS
    call_param.tools = None

    stream = await client.call(call_param)
    accumulated: list[str] = []
    final_text: str | None = None
    async for item in stream:
        if isinstance(item, message.AssistantTextDelta):
            accumulated.append(item.content)
        elif isinstance(item, message.AssistantMessage):
            final_text = message.join_text_parts(item.parts)
        elif isinstance(item, message.StreamErrorItem):
            raise RuntimeError(item.error)
    return final_text if final_text is not None else "".join(accumulated)


@register(tools.LOOK_AT)
class LookAtTool(ToolABC):
    class LookAtArguments(BaseModel):
        file_path: str
        question: str
        region: list[int] | None = Field(default=None)

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=False)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.LOOK_AT,
            type="function",
            description=load_desc(Path(__file__).parent / "look_at_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The absolute path to the local image file to inspect",
                    },
                    "question": {
                        "type": "string",
                        "description": "Your question or request about the image, e.g. 'Describe the page layout' or 'What does the error dialog say?'",
                    },
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                        "description": (
                            "Optional [x1, y1, x2, y2] crop region in pixel coordinates of the original image, "
                            "applied before any downscaling so the region keeps full resolution. "
                            "Use it to zoom into small text or details. Coordinates are clamped to the image bounds."
                        ),
                    },
                },
                "required": ["file_path", "question"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = LookAtTool.LookAtArguments.model_validate_json(arguments)
        except (ValidationError, ValueError) as e:
            log_debug(f"LookAtTool: invalid arguments: {e}")
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {e}")
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: LookAtTool.LookAtArguments, context: ToolContext) -> message.ToolResultMessage:
        file_path = str(resolve_workspace_path(args.file_path, context.work_dir))

        if is_directory(file_path):
            return _error("Illegal operation on a directory: LookAt")
        if not file_exists(file_path):
            return _error("File does not exist.")
        if not _is_supported_image_file(file_path):
            return _error(
                f"Unsupported image file extension: {Path(file_path).suffix or '(none)'}. "
                "Supported: .png, .jpg, .jpeg, .gif, .webp"
            )
        if args.region is not None and len(args.region) != 4:
            return _error("region must be [x1, y1, x2, y2] (exactly 4 integers).")

        try:
            size_bytes = Path(file_path).stat().st_size
        except OSError:
            size_bytes = 0
        if size_bytes > READ_MAX_IMAGE_BYTES:
            size_mb = size_bytes / (1024 * 1024)
            limit_mb = READ_MAX_IMAGE_BYTES / (1024 * 1024)
            return _error(f"Image size ({size_mb:.2f}MB) exceeds maximum supported size ({limit_mb:.2f}MB).")

        try:
            config = load_config()
        except (OSError, ValueError) as e:
            return _error(f"Failed to load config: {e}")
        candidate = _resolve_vision_candidate(config)
        if candidate is None:
            return _error(
                "No vision-capable fast model is available. "
                "Configure a multimodal model under `fast_model` in klaude-config.yaml."
            )

        crop_note = ""
        try:
            image_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
            if args.region is not None:
                image_bytes, applied_region, original_size = await asyncio.to_thread(
                    _crop_region_to_png, image_bytes, args.region
                )
                crop_note = (
                    f"[region {applied_region[0]},{applied_region[1]},{applied_region[2]},{applied_region[3]}"
                    f" of {original_size[0]}x{original_size[1]}] "
                )
                source_part: message.ImageURLPart | message.ImageFilePart = message.ImageURLPart(
                    url=f"data:image/png;base64,{b64encode(image_bytes).decode('ascii')}",
                    source_file_path=file_path,
                )
            else:
                mime_type = detect_mime_type_from_bytes(image_bytes) or _image_mime_type(file_path)
                source_part = message.ImageFilePart(file_path=file_path, mime_type=mime_type)
            # Snapshot compression is CPU-bound; keep the event loop moving.
            image_part = await asyncio.to_thread(
                freeze_image_to_file_for_history,
                source_part,
                images_dir=_session_images_dir(context),
            )
            if image_part is None:
                raise OSError("failed to snapshot image")
        except Exception as exc:
            return _error(f"Failed to read image file: {exc}")

        try:
            answer = await asyncio.wait_for(
                _ask_vision_model(candidate, image_part, args.question),
                timeout=LOOK_AT_TIMEOUT_SEC,
            )
        except TimeoutError:
            return _error(f"Vision model call timed out after {LOOK_AT_TIMEOUT_SEC}s.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _error(f"Vision model call failed ({candidate.selector}): {exc}")

        if not answer.strip():
            return _error(f"Vision model ({candidate.selector}) returned no text.")

        return message.ToolResultMessage(
            status="success",
            output_text=f"{crop_note}{answer.strip()}",
            ui_extra=ImageUIExtra(file_path=image_part.file_path),
        )
