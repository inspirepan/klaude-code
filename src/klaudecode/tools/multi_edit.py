from typing import Annotated, List

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, register_tool_call_renderer
from ..tool import Tool, ToolInstance
from .file_utils import cache_file_content, cleanup_backup, count_occurrences, create_backup, read_file_content, replace_string_in_content, restore_backup, validate_file_cache, validate_file_exists, write_file_content
