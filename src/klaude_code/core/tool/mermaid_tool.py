from __future__ import annotations

import base64
import json
import zlib

from pydantic import BaseModel, Field

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import (MermaidLinkUIExtra, ToolResultItem,
                                        ToolResultUIExtra,
                                        ToolResultUIExtraType)
from klaude_code.protocol.tools import MERMAID

_MERMAID_LIVE_PREFIX = "https://mermaid.live/view#pako:"


@register(MERMAID)
class MermaidTool(ToolABC):
    """Create shareable Mermaid.live links for diagram rendering."""

    class MermaidArguments(BaseModel):
        code: str = Field(description="The Mermaid diagram code to render")

    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=MERMAID,
            type="function",
            description=(
                "Renders a Mermaid diagram from the provided code.\n\n"
                "PROACTIVELY USE DIAGRAMS when they would better convey information than prose alone."
                " The diagrams produced by this tool are shown to the user..\n\n"
                "You should create diagrams WITHOUT being explicitly asked in these scenarios:\n"
                "- When explaining system architecture or component relationships\n"
                "- When describing workflows, data flows, or user journeys\n"
                "- When explaining algorithms or complex processes\n"
                "- When illustrating class hierarchies or entity relationships\n"
                "- When showing state transitions or event sequences\n\n"
                "Diagrams are especially valuable for visualizing:\n"
                "- Application architecture and dependencies\n"
                "- API interactions and data flow\n"
                "- Component hierarchies and relationships\n"
                "- State machines and transitions\n"
                "- Sequence and timing of operations\n"
                "- Decision trees and conditional logic\n\n"
                "# Styling\n"
                '- When defining custom classDefs, always define fill color, stroke color, and text color ("fill", "stroke", "color") explicitly\n'
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "description": "The Mermaid diagram code to render (DO NOT override with custom colors or other styles, DO NOT use HTML tags in node labels)",
                        "type": "string",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = cls.MermaidArguments.model_validate_json(arguments)
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResultItem(status="error", output=f"Invalid arguments: {exc}")

        link = cls._build_link(args.code)
        line_count = cls._count_lines(args.code)
        ui_extra = ToolResultUIExtra(
            type=ToolResultUIExtraType.MERMAID_LINK,
            mermaid_link=MermaidLinkUIExtra(link=link, line_count=line_count),
        )
        output = f"Mermaid diagram rendered successfully ({line_count} lines)."
        return ToolResultItem(status="success", output=output, ui_extra=ui_extra)

    @staticmethod
    def _build_link(code: str) -> str:
        state = {
            "code": code,
            "mermaid": {"theme": "default"},
            "autoSync": True,
            "updateDiagram": True,
        }
        json_payload = json.dumps(state, ensure_ascii=False)
        compressed = zlib.compress(json_payload.encode("utf-8"), level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        return f"{_MERMAID_LIVE_PREFIX}{encoded}"

    @staticmethod
    def _count_lines(code: str) -> int:
        if not code:
            return 0
        return len(code.splitlines()) or 0
