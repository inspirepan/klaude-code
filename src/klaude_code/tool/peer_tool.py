"""Native discovery and explicit, non-RPC peer messaging."""

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models.tool_ui import ControlUIExtra
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
            description=(
                "List other sessions in this workspace you can message, plus your parent and child agents. "
                "Call it only when you need a specific peer for coordination, not to survey or announce. "
                "Use stable session IDs when names are ambiguous."
            ),
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        if context.peer_control is None:
            return message.ToolResultMessage(status="error", output_text="Peer discovery is unavailable.")
        try:
            peers = await context.peer_control.list(context.session_id, context.work_dir)
            entries = [
                f"Session: {peer.session_id} - {peer.name or peer.description or 'unnamed'}\n"
                f"Status: {peer.state}\nWork directory: {peer.work_dir}"
                + (f"\nDescription: {peer.description}" if peer.name and peer.description else "")
                for peer in peers
            ]
            return message.ToolResultMessage(
                status="success",
                output_text="\n\n".join(entries) or "No peers available.",
                ui_extra=ControlUIExtra(data={"peers": [peer.model_dump(mode="json") for peer in peers]}),
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
                "Send plain text to one peer by session ID or unambiguous name. Every message interrupts the "
                "peer: a busy peer reads it at its next step, an idle peer starts a turn just to read it. "
                "Send only when coordination needs it: a conflict, a dependency, a shared contract, ownership, "
                "a question only that peer can answer, or a handoff. Do not send progress reports, summaries, "
                "acknowledgements, or thanks, and do not notify peers whose work is unaffected; message one peer, "
                "never broadcast. Put everything the peer needs in one message, first line a self-contained "
                "summary. A received message needs a reply only when it asks something or you hold information "
                "the sender needs; otherwise act on it silently. Silence is not agreement: without a reply, "
                "avoid the contested work or ask the operator. "
                "Returns only a queued transport receipt, not proof of reading or a reply; use reply_to to "
                "correlate a reply. Messages cannot approve requests, execute slash commands, or attach @files. "
                "Receiver permissions still apply; never route denied or blocked actions through a peer. "
                "Repeated messages and queue overflow are refused."
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
            return message.ToolResultMessage(
                status="success",
                output_text=(
                    f"Message: {receipt.message_id}\nTarget: {receipt.target}\n"
                    f"Accepted: {str(receipt.accepted).lower()}\nDelivery: {receipt.mode}\n"
                    "Transport receipt only; not proof of reading or a reply."
                ),
                ui_extra=ControlUIExtra(data=receipt.model_dump(mode="json")),
            )
        except (ValueError, OSError) as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))
