from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.const import MERMAID_LIVE_PREFIX
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools


@register(tools.MERMAID)
class MermaidTool(ToolABC):
    """Create shareable Mermaid.live links for diagram rendering."""

    class MermaidArguments(BaseModel):
        code: str = Field(description="The Mermaid diagram code to render")

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MERMAID,
            type="function",
            description=load_desc(Path(__file__).parent / "mermaid_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "description": "The Mermaid diagram code to render (DO NOT use HTML tags in node labels)",
                        "type": "string",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        del context
        try:
            args = cls.MermaidArguments.model_validate_json(arguments)
        except Exception as exc:  # pragma: no cover - defensive
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")

        link = cls._build_link(args.code)
        line_count = cls._count_lines(args.code)
        ui_extra = model.MermaidLinkUIExtra(code=args.code, link=link, line_count=line_count)
        output = f"Mermaid diagram rendered successfully ({line_count} lines)."
        return message.ToolResultMessage(status="success", output_text=output, ui_extra=ui_extra)

    @staticmethod
    def _build_link(code: str) -> str:
        state = {
            "code": code,
            "mermaid": {"theme": "neutral"},
            "autoSync": True,
            "updateDiagram": True,
        }
        json_payload = json.dumps(state, ensure_ascii=False)
        compressed = zlib.compress(json_payload.encode("utf-8"), level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"{MERMAID_LIVE_PREFIX}{encoded}"

    @staticmethod
    def _count_lines(code: str) -> int:
        if not code:
            return 0
        return len(code.splitlines()) or 0
