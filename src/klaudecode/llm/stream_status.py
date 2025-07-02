import random
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from ..tui import ColorStyle


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

UPDATE_STATUS_TEXTS = ['Updating', 'Modifying', 'Changing', 'Refactoring', 'Transforming', 'Rewriting', 'Refining', 'Polishing', 'Tweaking', 'Adjusting', 'Fixing']
TODO_STATUS_TEXTS = ['Planning', 'Organizing', 'Structuring', 'Brainstorming', 'Strategizing', 'Outlining', 'Tracking']

TOOL_CALL_STATUS_TEXT_DICT = {
    'MultiEdit': UPDATE_STATUS_TEXTS,
    'Edit': UPDATE_STATUS_TEXTS,
    'Read': ['Exploring', 'Reading', 'Scanning', 'Analyzing', 'Inspecting', 'Examining', 'Studying'],
    'Write': ['Writing', 'Creating', 'Crafting', 'Composing', 'Generating'],
    'TodoWrite': TODO_STATUS_TEXTS,
    'TodoRead': TODO_STATUS_TEXTS,
    'LS': ['Exploring', 'Scanning', 'Browsing', 'Investigating', 'Surveying', 'Discovering', 'Wandering'],
    'Grep': ['Searching', 'Looking', 'Finding', 'Hunting', 'Tracking', 'Filtering', 'Digging'],
    'Glob': ['Searching', 'Looking', 'Finding', 'Matching', 'Collecting', 'Gathering', 'Harvesting'],
    'Bash': ['Executing', 'Running', 'Processing', 'Computing', 'Launching', 'Invoking', 'Commanding'],
    'ExitPlanMode': ['Planning'],
    'CommandPatternResult': ['Patterning'],
}


def text_status_str(status_str: str) -> Text:
    return Text(status_str, style=ColorStyle.CLAUDE)


def get_reasoning_status_text(seed: Optional[int] = None) -> Text:
    """Get random reasoning status text"""
    if seed is not None:
        random.seed(seed)
    status_str = random.choice(REASONING_STATUS_TEXT_LIST)
    return text_status_str(status_str)


def get_content_status_text(seed: Optional[int] = None) -> Text:
    """Get random content generation status text"""
    if seed is not None:
        random.seed(seed)
    status_str = random.choice(CONTENT_STATUS_TEXT_LIST)
    return text_status_str(status_str)


def get_upload_status_text(seed: Optional[int] = None) -> Text:
    """Get random upload status text"""
    if seed is not None:
        random.seed(seed)
    status_str = random.choice(UPLOAD_STATUS_TEXT_LIST)
    return text_status_str(status_str)


def get_tool_call_status_text(tool_name: str, seed: Optional[int] = None) -> Text:
    """
    Write -> Writing
    """
    if seed is not None:
        random.seed(seed)
    if tool_name in TOOL_CALL_STATUS_TEXT_DICT:
        status_str = random.choice(TOOL_CALL_STATUS_TEXT_DICT[tool_name])
    elif tool_name.startswith('mcp__'):
        status_str = 'Executing'
    elif tool_name.endswith('e'):
        status_str = f'{tool_name[:-1]}ing'
    else:
        status_str = f'{tool_name}ing'
    return text_status_str(status_str)
