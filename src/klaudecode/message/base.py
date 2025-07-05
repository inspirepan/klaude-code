import json
from typing import List, Literal, Optional, Tuple

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


class Attachment(BaseModel):
    type: Literal['text', 'image', 'directory'] = 'text'
    path: str
    content: str = ''
    is_directory: bool = False
    # Text file
    line_count: int = 0
    brief: List[Tuple[int, str]] = []  # line_number, line_content for UI display
    actual_range_str: str = ''  # actual range of the file for UI display
    truncated: bool = False

    # Image
    media_type: Optional[str] = None
    size_str: str = ''

    def get_content(self):
        if self.type == 'image':
            if self.path:
                return [
                    {'type': 'text', 'text': f'Following is the image from file: {self.path}, you DO NOT need to call Read tool again.'},
                    {'type': 'image', 'source': {'type': 'base64', 'data': self.content, 'media_type': self.media_type}},
                ]
            else:
                return [{'type': 'image', 'source': {'type': 'base64', 'data': self.content, 'media_type': self.media_type}}]
        elif self.type == 'directory':
            attachment_text = f'''Called the LS tool with the following input: {{"path":"{self.path}"}}
Result of calling the LS tool: "{self.content}"'''
            return [{'type': 'text', 'text': attachment_text}]
        else:
            attachment_text = f'''Called the Read tool with the following input: {{"file_path":"{self.path}"}}
Result of calling the Read tool: "{self.content}"'''
            return [{'type': 'text', 'text': attachment_text}]


class BasicMessage(BaseModel):
    role: str
    content: str = ''
    removed: bool = False
    extra_data: Optional[dict] = None
    attachments: Optional[List[Attachment]] = None

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
                        # Count the full JSON structure that gets sent to API
                        total_text += json.dumps(item)
                elif isinstance(item, str):
                    total_text += item

        # Add role overhead (approximation)
        total_text = f'{self.role}: {total_text}'

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

    def append_attachment(self, attachment: Attachment):
        if not self.attachments:
            self.attachments = []
        self.attachments.append(attachment)
