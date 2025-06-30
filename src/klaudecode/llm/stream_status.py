import random
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

STATUS_TEXT_LENGTH = 12


class StreamStatus(BaseModel):
    phase: Literal['upload', 'think', 'content', 'tool_call', 'completed'] = 'upload'
    tokens: int = 0
    tool_names: List[str] = Field(default_factory=list)


REASONING_STATUS_TEXT_LIST = [
    'Thinking',
    'Reflecting',
    'Reasoning',
]

CONTENT_STATUS_TEXT_LIST = [
    'Composing',
    'Crafting',
    'Formulating',
    'Responding',
    'Articulating',
    'Expressing',
    'Detailing',
    'Explaining',
    'Describing',
    'Pondering',
    'Considering',
    'Analyzing',
    'Contemplating',
    'Deliberating',
    'Evaluating',
    'Assessing',
    'Examining',
]

UPLOAD_STATUS_TEXT_LIST = [
    'Waiting',
    'Loading',
    'Connecting',
    'Launching',
]


def get_reasoning_status_text(seed: Optional[int] = None) -> str:
    """Get random reasoning status text"""
    if seed is not None:
        random.seed(seed)
    return random.choice(REASONING_STATUS_TEXT_LIST) + '...'


def get_content_status_text(seed: Optional[int] = None) -> str:
    """Get random content generation status text"""
    if seed is not None:
        random.seed(seed)
    return random.choice(CONTENT_STATUS_TEXT_LIST) + '...'


def get_upload_status_text(seed: Optional[int] = None) -> str:
    """Get random upload status text"""
    if seed is not None:
        random.seed(seed)
    return random.choice(UPLOAD_STATUS_TEXT_LIST) + '...'
