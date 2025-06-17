from typing import Dict, List, Literal, Optional, Union

import tiktoken
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam
from pydantic import BaseModel, Field, computed_field, model_validator
from rich.abc import RichRenderable
from rich.console import Group
from rich.text import Text

from .input import InputModeEnum
from .tui import render_markdown, render_message, render_suffix
from .utils import truncate_text

# Initialize tiktoken encoder for GPT-4
_encoder = tiktoken.encoding_for_model("gpt-4")


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken"""
    if not text:
        return 0
    return len(_encoder.encode(text))


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

    def to_openai(self) -> ChatCompletionMessageParam:
        return {"role": self.role, "content": self.content or ""}

    def __rich__(self):
        return ""  # System message is not displayed.


class UserMessage(BasicMessage):
    role: Literal["user"] = "user"
    mode: Literal[
        InputModeEnum.NORMAL,
        InputModeEnum.PLAN,
        InputModeEnum.BASH,
        InputModeEnum.MEMORY,
        InputModeEnum.INTERRUPTED,
    ] = InputModeEnum.NORMAL
    suffix: Optional[str] = None
    system_reminder: Optional[str] = None
    suffix: Optional[str] = None
    system_reminder: Optional[str] = None

    _mark_style: Optional[str] = None
    _mark: Optional[str] = None
    _style: Optional[str] = None

    _MODE_CONF = {
        InputModeEnum.NORMAL: {"_mark_style": None, "_mark": ">", "_style": None},
        InputModeEnum.PLAN: {"_mark_style": None, "_mark": ">", "_style": None},
        InputModeEnum.BASH: {
            "_mark_style": "magenta",
            "_mark": "!",
            "_style": "magenta",
        },
        InputModeEnum.MEMORY: {"_mark_style": "blue", "_mark": "#", "_style": "blue"},
        InputModeEnum.INTERRUPTED: {
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
            "content": self.content or "",
        }  # TODO: add suffix and system_reminder

    def __rich__(self):
        user_msg = render_message(
            self.content,
            style=self._style,
            mark_style=self._mark_style,
            mark=self._mark,
            status="processing",
        )
        if self.suffix:
            return Group(user_msg, render_suffix(self.suffix))
        return user_msg


class ToolCallMessage(BaseModel):
    id: str
    tool_name: str
    tool_args: Union[Dict, str]

    nice_args: str = ""
    status: Literal["processing", "success", "error"] = "processing"
    hide_args: bool = False

    @computed_field
    @property
    def tokens(self) -> int:
        """Calculate token count for the tool call"""
        # Count tokens for function name and arguments
        func_tokens = count_tokens(self.tool_name)

        # Handle arguments as string or dict
        if isinstance(self.tool_args, str):
            args_tokens = count_tokens(self.tool_args)
        else:
            args_tokens = count_tokens(str(self.tool_args))

        return func_tokens + args_tokens

    @classmethod
    def from_openai_tool_call(cls, tool_call) -> "ToolCallMessage":
        return cls(
            id=tool_call.id,
            function_name=tool_call.function.name,
            function_arguments=tool_call.function.arguments,
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
    # TODO: add thinking part
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
        content_tokens = count_tokens(self.content) if self.content else 0
        tool_call_tokens = sum(tc.tokens for tc in self.tool_calls.values())
        return content_tokens + tool_call_tokens

    def to_openai(self) -> ChatCompletionMessageParam:
        result = {"role": self.role, "content": self.content or ""}
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
    def from_openai(cls, message: ChatCompletionMessage) -> "AIMessage":
        tool_calls = {}
        if message.tool_calls:
            tool_calls = {
                tc.id: ToolCallMessage.from_openai_tool_call(tc)
                for tc in message.tool_calls
            }

        content = message.content or ""
        return cls(
            content=content,
            tool_calls=tool_calls,
            nice_content=render_markdown(content) if content else "",
        )

    def __rich__(self):
        return render_message(self.nice_content or self.content, mark_style="white")


class ToolMessage(BasicMessage):
    role: Literal["tool"] = "tool"
    tool_call: ToolCallMessage
    subagent_tool_calls: List[ToolCallMessage] = Field(
        default_factory=list
    )  # For sub-agent tool calls

    class Config:
        arbitrary_types_allowed = True

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            "role": self.role,
            "content": self.content,
            "tool_call_id": self.tool_call.id,
        }

    def __rich__(self):
        content = (
            truncate_text(self.content.strip()) if self.content else "(No content)"
        )
        return Group(
            self.tool_call,
            *[c.get_suffix_renderable() for c in self.subagent_tool_calls],
            render_suffix(content, error=self.tool_call.status == "error"),
        )
