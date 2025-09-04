# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportUnknownVariableType=false


import json

from anthropic.types.beta.beta_message_param import BetaMessageParam
from anthropic.types.beta.beta_text_block_param import BetaTextBlockParam
from anthropic.types.beta.beta_tool_param import BetaToolParam

from codex_mini.protocol import llm_parameter, model


def convert_history_to_input(
    history: list[model.ResponseItem],
) -> list[BetaMessageParam]:
    messages: list[BetaMessageParam] = []
    for group_kind, group in model.group_reponse_items_gen(history):
        match group_kind:
            case "user":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": item.content,
                            }
                            for item in group
                            if isinstance(item, model.UserMessage)
                        ],
                    }
                )
            case "tool":
                if len(group) == 0 or not isinstance(group[0], model.ToolMessage):
                    continue
                tool_message = group[0]
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_message.call_id,
                                "is_error": tool_message.status == "error",
                                "content": tool_message.content,
                            }
                        ],
                    }
                )
            case "assistantish":
                assistant_message = {
                    "role": "assistant",
                    "content": [],
                }
                for item in group:
                    match item:
                        case model.AssistantMessage() as assistant_message_item:
                            assistant_message["content"].append(
                                {
                                    "type": "text",
                                    "text": assistant_message_item.content,
                                }
                            )
                        case model.ToolCallItem() as tool_call_item:
                            assistant_message["content"].append(
                                {
                                    "type": "tool_use",
                                    "id": tool_call_item.call_id,
                                    "name": tool_call_item.name,
                                    "input": json.loads(tool_call_item.arguments)
                                    if tool_call_item.arguments
                                    else None,
                                }
                            )
                        case model.ReasoningItem() as reasoning_item:
                            assistant_message["content"].append(
                                {
                                    "type": "thinking",
                                    "thinking": reasoning_item.content,
                                    "signature": reasoning_item.encrypted_content,
                                }
                            )
                        case _:
                            pass

                messages.append(assistant_message)
            case "other":
                pass
    if len(messages) > 0:
        last_message = messages[-1]
        content_list = list(last_message.get("content", []))
        if content_list:
            last_content_part = content_list[-1]
            if last_content_part.get("type", "") in ["text", "tool_result", "tool_use"]:
                last_content_part["cache_control"] = {"type": "ephemeral"}  # type: ignore
    return messages


def convert_system_to_input(system: str | None) -> list[BetaTextBlockParam]:
    if system is None:
        return []
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def convert_tool_schema(
    tools: list[llm_parameter.ToolSchema] | None,
) -> list[BetaToolParam]:
    if tools is None:
        return []
    return [
        {
            "input_schema": tool.parameters,
            "type": "custom",
            "name": tool.name,
            "description": tool.description,
        }
        for tool in tools
    ]
