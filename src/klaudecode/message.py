from typing import Dict, List, Literal, Optional, Union

from openai.types.chat import (ChatCompletionMessageParam,
                               ChatCompletionMessageToolCall)
from pydantic import BaseModel, Field, computed_field, model_validator
from rich.abc import RichRenderable
from rich.console import Group
from rich.text import Text

from .config import ConfigModel
from .llm import LLMResponse, count_tokens
from .tui import format_style, render_markdown, render_message, render_suffix
from .utils import truncate_text


class BasicMessage(BaseModel):
    role: str
    content: Optional[str] = "<empty>"
    removed: bool = False  # A message is removed when /compact called.

    @computed_field
    @property
    def tokens(self) -> int:
        """Calculate token count for the message content"""
        return count_tokens(self.content)

    def to_openai(self) -> ChatCompletionMessageParam:
        raise NotImplementedError


class SystemMessage(BasicMessage):
    role: Literal["system"] = "system"
    cached: bool = False

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            "role": self.role,
            "content": [
                {
                    "type": "text",
                    "text": self.content,
                    "cache_control": {
                        "type": "ephemeral"
                    } if self.cached else None,
                }
            ]
        }

    def __rich__(self):
        return ""  # System message is not displayed.


class UserMessage(BasicMessage):
    role: Literal["user"] = "user"
    mode: Literal[
        "normal",
        "plan",
        "bash",
        "memory",
        "interrupted",
    ] = "normal"
    suffix: Optional[Union[str, ConfigModel]] = None
    system_reminder: Optional[str] = None

    _mark_style: Optional[str] = None
    _mark: Optional[str] = None
    _style: Optional[str] = None

    _MODE_CONF = {
        "normal": {"_mark_style": None, "_mark": ">", "_style": None},
        "plan": {"_mark_style": None, "_mark": ">", "_style": None},
        "bash": {
            "_mark_style": "magenta",
            "_mark": "!",
            "_style": "magenta",
        },
        "memory": {"_mark_style": "blue", "_mark": "#", "_style": "blue"},
        "interrupted": {
            "_mark_style": "yellow",
            "_mark": "⏺",
            "_style": "yellow",
        },
    }

    @model_validator(mode="after")
    def _inject_private_defaults(self):
        conf = self._MODE_CONF[self.mode]
        for k, v in conf.items():
            setattr(self, k, v)
        return self

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            "role": self.role,
            "content": self.content or "<empty>",
        }  # TODO: add suffix and system_reminder

    def __rich__(self):
        user_msg = render_message(
            self.content,
            style=self._style,
            mark_style=self._mark_style,
            mark=self._mark,
        )
        if self.suffix:
            return Group(user_msg, render_suffix(self.suffix))
        return user_msg


class ToolCallMessage(BaseModel):
    id: str
    tool_name: str
    tool_args: str

    nice_args: str = ""
    status: Literal["processing", "success", "error"] = "processing"
    hide_args: bool = False

    @computed_field
    @property
    def tokens(self) -> int:
        func_tokens = count_tokens(self.tool_name)
        args_tokens = count_tokens(self.tool_args)
        return func_tokens + args_tokens

    @classmethod
    def from_openai_tool_call(cls, tool_call: ChatCompletionMessageToolCall) -> "ToolCallMessage":
        return cls(
            id=tool_call.id,
            tool_name=tool_call.function.name,
            tool_args=tool_call.function.arguments,
            nice_content="",
        )

    def __rich__(self):
        args = "" if self.hide_args else self.nice_args or self.tool_args
        msg = Text.assemble((self.tool_name, "bold"), "(", args, ")")
        return render_message(msg, mark_style="green", status=self.status)

    def get_suffix_renderable(self) -> RichRenderable:
        args = "" if self.hide_args else self.nice_args or self.tool_args
        msg = Text.assemble((self.tool_name, "bold"), "(", args, ")")
        return render_suffix(msg, error=self.status == "error")


class AIMessage(BasicMessage):
    role: Literal["assistant"] = "assistant"
    reasoning_content: Optional[str] = ""
    tool_calls: dict[str, ToolCallMessage] = {}  # id -> ToolCall
    nice_content: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        if self.content and not self.nice_content:
            self.nice_content = render_markdown(self.content)

    @computed_field
    @property
    def tokens(self) -> int:
        """Calculate token count for AI message including tool calls"""
        content_tokens = count_tokens(self.content + self.reasoning_content)
        tool_call_tokens = sum(tc.tokens for tc in self.tool_calls.values())
        return content_tokens + tool_call_tokens

    def to_openai(self) -> ChatCompletionMessageParam:
        result = {"role": self.role, "content": self.content or "<empty>"}
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": tc.tool_args,
                    },
                }
                for tc in self.tool_calls.values()
            ]
        return result

    @classmethod
    def from_llm_response(cls, llm_response: LLMResponse) -> "AIMessage":
        tool_calls = {}
        if llm_response.tool_calls:
            tool_calls = {tc.id: ToolCallMessage.from_openai_tool_call(tc) for tc in llm_response.tool_calls}
        return cls(
            content=llm_response.content,
            reasoning_content=llm_response.reasoning_content,
            tool_calls=tool_calls,
            nice_content=render_markdown(llm_response.content) if llm_response.content else "",
        )

    def __rich__(self):
        if self.reasoning_content:
            return Group(
                render_message(format_style("Thinking...", "gray"), mark="✻", mark_style="white", style="italic"),
                render_message(format_style(self.reasoning_content, "gray"), mark="", mark_style="white", style="italic"),
                "",
                render_message(self.nice_content or self.content, mark_style="white", style="orange")
            )
        return render_message(self.nice_content or self.content, mark_style="white", style="orange")


class ToolMessage(BasicMessage):
    role: Literal["tool"] = "tool"
    tool_call: ToolCallMessage
    subagent_tool_calls: List[ToolCallMessage] = Field(default_factory=list)  # For sub-agent tool calls

    class Config:
        arbitrary_types_allowed = True

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            "role": self.role,
            "content": self.content,
            "tool_call_id": self.tool_call.id,
        }

    def __rich__(self):
        content = truncate_text(self.content.strip()) if self.content else "(No content)"
        return Group(
            self.tool_call,
            *[c.get_suffix_renderable() for c in self.subagent_tool_calls],
            render_suffix(content, error=self.tool_call.status == "error"),
        )
