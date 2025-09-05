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
    history: list[model.ConversationItem],
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
                            if isinstance(item, model.UserMessageItem)
                        ],
                    }
                )
            case "tool":
                if len(group) == 0 or not isinstance(group[0], model.ToolResultItem):
                    continue
                tool_result = group[0]
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_result.call_id,
                                "is_error": tool_result.status == "error",
                                "content": tool_result.output,
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
                        case model.AssistantMessageItem() as a:
                            assistant_message["content"].append(
                                {
                                    "type": "text",
                                    "text": a.content,
                                }
                            )
                        case model.ToolCallItem() as t:
                            assistant_message["content"].append(
                                {
                                    "type": "tool_use",
                                    "id": t.call_id,
                                    "name": t.name,
                                    "input": json.loads(t.arguments) if t.arguments else None,
                                }
                            )
                        case model.ReasoningItem() as r:
                            assistant_message["content"].append(
                                {
                                    "type": "thinking",
                                    "thinking": r.content,
                                    "signature": r.encrypted_content,
                                }
                            )
                        case _:
                            pass

                messages.append(assistant_message)
            case "other":
                pass

    # Cache control
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
