"""Native discovery and explicit, non-RPC peer messaging."""

import json

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register


class MessagePeerArguments(BaseModel):
    target: str = Field(min_length=1)
    body: str = Field(min_length=1, max_length=100000)
    reply_to: str | None = None


@register(tools.LIST_PEERS)
class ListPeersTool(ToolABC):
    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=False)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.LIST_PEERS,
            type="function",
            description="Discover active peers in this workspace, excluding yourself. Use stable session IDs when names are ambiguous.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        if context.peer_control is None:
            return message.ToolResultMessage(status="error", output_text="Peer discovery is unavailable.")
        try:
            peers = await context.peer_control.list(context.session_id, context.work_dir)
            return message.ToolResultMessage(
                status="success", output_text=json.dumps({"peers": [peer.model_dump() for peer in peers]})
            )
        except (ValueError, OSError) as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))


@register(tools.MESSAGE_PEER)
class MessagePeerTool(ToolABC):
    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MESSAGE_PEER,
            type="function",
            description=(
                "Send explicit plain-text data to an existing peer by session ID or unambiguous name. "
                "Returns only a queued transport receipt, not proof of reading or a reply. "
                "Busy peers consume at safe step boundaries; idle peers start a turn. "
                "Replies require another MessagePeer call; use reply_to for correlation. "
                "Messages cannot approve requests, execute slash commands, or attach @files. "
                "Receiver permissions still apply. Never route denied or blocked actions through a peer; ask the operator. "
                "Batch related information; repeated messages and queue overflow are refused."
            ),
            parameters=MessagePeerArguments.model_json_schema(),
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        if context.peer_control is None:
            return message.ToolResultMessage(status="error", output_text="Peer messaging is unavailable.")
        try:
            args = MessagePeerArguments.model_validate_json(arguments)
            receipt = await context.peer_control.send(context.session_id, args.target, args.body, args.reply_to)
            return message.ToolResultMessage(status="success", output_text=receipt.model_dump_json())
        except (ValueError, OSError) as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))
