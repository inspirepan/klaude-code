import json
from typing import Optional

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        import tiktoken

        _encoder = tiktoken.encoding_for_model('gpt-4')
    return _encoder


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_get_encoder().encode(text))


class CompletionUsage(BaseModel):
    completion_tokens: int
    prompt_tokens: int
    total_tokens: int


class BasicMessage(BaseModel):
    role: str
    content: str = ''
    removed: bool = False
    usage: Optional[CompletionUsage] = None
    extra_data: Optional[dict] = None

    def get_content(self):
        return [{'type': 'text', 'text': self.content}]

    @property
    def tokens(self) -> int:
        content_list = self.get_content()
        total_text = ''

        if isinstance(content_list, str):
            total_text = content_list
        elif isinstance(content_list, list):
            for item in content_list:
                if isinstance(item, dict):
                    if item.get('type') == 'text':
                        total_text += item.get('text', '')
                    elif item.get('type') == 'thinking':
                        total_text += item.get('thinking', '')
                    elif item.get('type') == 'tool_use':
                        tool_name = item.get('name', '')
                        tool_input = json.dumps(item.get('input', {})) if item.get('input') else ''
                        total_text += f'{tool_name}({tool_input})'
                elif isinstance(item, str):
                    total_text += item

        return count_tokens(total_text)

    def to_openai(self) -> ChatCompletionMessageParam:
        raise NotImplementedError

    def to_anthropic(self):
        raise NotImplementedError

    def set_extra_data(self, key: str, value: object):
        if not self.extra_data:
            self.extra_data = {}
        self.extra_data[key] = value

    def append_extra_data(self, key: str, value: object):
        if not self.extra_data:
            self.extra_data = {}
        if key not in self.extra_data:
            self.extra_data[key] = []
        self.extra_data[key].append(value)

    def get_extra_data(self, key: str, default: object = None) -> object:
        if not self.extra_data:
            return default
        if key not in self.extra_data:
            return default
        return self.extra_data[key]
