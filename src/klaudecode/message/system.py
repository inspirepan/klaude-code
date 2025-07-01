from typing import Literal

from anthropic.types import TextBlockParam
from openai.types.chat import ChatCompletionMessageParam

from .base import BasicMessage


class SystemMessage(BasicMessage):
    role: Literal['system'] = 'system'
    cached: bool = False

    def get_content(self):
        return [
            {
                'type': 'text',
                'text': self.content,
                'cache_control': {'type': 'ephemeral'} if self.cached else None,
            }
        ]

    def get_anthropic_content(self):
        if self.cached:
            return {
                'type': 'text',
                'text': self.content,
                'cache_control': {'type': 'ephemeral'},
            }
        return {
            'type': 'text',
            'text': self.content,
        }

    def to_openai(self) -> ChatCompletionMessageParam:
        return {
            'role': 'system',
            'content': self.get_content(),
        }

    def to_anthropic(self) -> TextBlockParam:
        return self.get_anthropic_content()

    def __rich_console__(self, console, options):
        return
        yield

    def __bool__(self):
        return bool(self.content)
