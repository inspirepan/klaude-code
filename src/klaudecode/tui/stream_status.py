import random
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from . import ColorStyle


class StreamStatus(BaseModel):
    phase: Literal['upload', 'think', 'content', 'tool_call', 'completed'] = 'upload'
    tokens: int = 0
    tool_names: List[str] = Field(default_factory=list)


REASONING_STATUS_TEXT_LIST = [
    'Thinking',
    'Reasoning',
    'Meditating',
    'Contemplating',
    'Pondering',
    'Reflecting',
    'Cogitating',
    'Mulling',
]

CONTENT_STATUS_TEXT_LIST = [
    'Composing',
    'Crafting',
    'Weaving',
    'Spinning',
    'Painting',
    'Sculpting',
    'Brewing',
    'Conjuring',
    'Distilling',
    'Manifesting',
    'Articulating',
    'Creating',
    'Generating',
    'Forming',
    'Hatching',
    'Ideating',
    'Synthesizing',
    'Transmuting',
    'Musing',
]

UPLOAD_STATUS_TEXT_LIST = [
    'Launching',
    'Booting',
    'Activating',
    'Engaging',
    'Summoning',
    'Awakening',
    'Initializing',
    'Coalescing',
    'Mustering',
    'Reticulating',
    'Vibing',
    'Cerebrating',
]

EDIT_STATUS_TEXTS = [
    'Updating',
    'Refining',
    'Polishing',
    'Tweaking',
    'Enchanting',
    'Transforming',
    'Evolving',
    'Reshaping',
    'Forging',
    'Actualizing',
    'Effecting',
    'Finagling',
    'Determining',
]
TODO_STATUS_TEXTS = [
    'Planning',
    'Scheming',
    'Plotting',
    'Strategizing',
    'Blueprinting',
    'Choreographing',
    'Masterminding',
    'Accomplishing',
    'Actioning',
    'Doing',
    'Working',
    'Considering',
    'Deliberating',
]

TOOL_CALL_STATUS_TEXT_DICT = {
    'MultiEdit': EDIT_STATUS_TEXTS,
    'Edit': EDIT_STATUS_TEXTS,
    'Read': ['Exploring', 'Deciphering', 'Absorbing', 'Devouring', 'Savoring', 'Digesting', 'Unraveling', 'Percolating', 'Simmering', 'Inferring'],
    'Write': ['Writing', 'Inscribing', 'Birthing', 'Channeling', 'Baking', 'Cooking', 'Marinating', 'Stewing'],
    'TodoWrite': TODO_STATUS_TEXTS,
    'TodoRead': TODO_STATUS_TEXTS,
    'LS': ['Wandering', 'Discovering', 'Venturing', 'Roaming', 'Adventuring', 'Pathfinding', 'Moseying', 'Puttering'],
    'Grep': ['Searching', 'Hunting', 'Stalking', 'Pursuing', 'Chasing', 'Seeking', 'Detecting', 'Herding', 'Noodling'],
    'Glob': ['Gathering', 'Harvesting', 'Collecting', 'Reaping', 'Foraging', 'Accumulating', 'Hoarding', 'Schlepping', 'Shucking', 'Smooshing'],
    'Bash': ['Executing', 'Commanding', 'Wielding', 'Casting', 'Invoking', 'Computing', 'Calculating', 'Crunching', 'Churning', 'Processing', 'Ruminating'],
    'exit_plan_mode': ['Reporting'],
    'CommandPatternResult': ['Patterning'],
    'Task': ['Delegating', 'Dispatching', 'Outsourcing', 'Assigning', 'Coordinating', 'Hustling', 'Honking', 'Clauding', 'Orchestrating'],
}


def text_status_str(status_str: str) -> Text:
    return Text(status_str, style=ColorStyle.STATUS)


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
