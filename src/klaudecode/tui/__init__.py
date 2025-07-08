# Re-export all public APIs to maintain backward compatibility
from rich.text import Text

from .colors import ColorStyle
from .console import ConsoleProxy, console
from .markdown_renderer import render_markdown
from .renderers import get_tip, render_grid, render_hello, render_logo, render_message, render_suffix, render_tips, truncate_middle_text
from .status import INTERRUPT_TIP, DotsStatus, render_dot_status
from .utils import clear_last_line, get_inquirer_style, get_prompt_toolkit_color, get_prompt_toolkit_style

__all__ = [
    # Colors and themes
    'ColorStyle',
    # Console
    'ConsoleProxy',
    'console',
    # Renderers
    'get_tip',
    'render_grid',
    'render_hello',
    'render_markdown',
    'render_message',
    'render_suffix',
    'truncate_middle_text',
    'render_logo',
    'render_tips',
    # Status
    'INTERRUPT_TIP',
    'DotsStatus',
    'render_dot_status',
    # Utils
    'clear_last_line',
    'get_inquirer_style',
    'get_prompt_toolkit_color',
    'get_prompt_toolkit_style',
    # Rich re-exports
    'Text',
]
