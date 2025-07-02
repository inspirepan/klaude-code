from enum import Enum

from rich.style import Style
from rich.theme import Theme


class ColorStyle(str, Enum):
    # AI and user interaction
    AI_MESSAGE = 'ai_message'
    AI_THINKING = 'ai_thinking'
    CLAUDE = 'claude'
    # For status indicators
    ERROR = 'error'
    SUCCESS = 'success'
    WARNING = 'warning'
    INFO = 'info'
    HIGHLIGHT = 'highlight'
    MAIN = 'main'
    MUTED = 'muted'
    SEPARATOR = 'separator'
    TODO_COMPLETED = 'todo_completed'
    TODO_IN_PROGRESS = 'todo_in_progress'
    # Tools and agents
    AGENT_BORDER = 'agent_border'
    # Code
    DIFF_REMOVED_LINE = 'diff_removed_line'
    DIFF_ADDED_LINE = 'diff_added_line'
    DIFF_REMOVED_CHAR = 'diff_removed_char'
    DIFF_ADDED_CHAR = 'diff_added_char'
    CONTEXT_LINE = 'context_line'
    INLINE_CODE = 'inline_code'
    # Prompt toolkit colors
    INPUT_PLACEHOLDER = 'input_placeholder'
    COMPLETION_MENU = 'completion_menu'
    COMPLETION_SELECTED = 'completion_selected'
    # Input mode colors
    BASH_MODE = 'bash_mode'
    MEMORY_MODE = 'memory_mode'
    PLAN_MODE = 'plan_mode'
    # Markdown
    H2 = 'h1'

    @property
    def bold(self) -> Style:
        # Import here to avoid circular import
        from .console import console

        return console.console.get_style(self.value) + Style(bold=True)

    @property
    def italic(self) -> Style:
        # Import here to avoid circular import
        from .console import console

        return console.console.get_style(self.value) + Style(italic=True)

    @property
    def bold_italic(self) -> Style:
        # Import here to avoid circular import
        from .console import console

        return console.console.get_style(self.value) + Style(bold=True, italic=True)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


light_theme = Theme(
    {
        # AI and user interaction
        ColorStyle.AI_MESSAGE: 'rgb(181,105,72)',
        ColorStyle.AI_THINKING: 'rgb(62,99,153)',
        ColorStyle.CLAUDE: 'rgb(214,119,86)',
        # Status indicators
        ColorStyle.ERROR: 'rgb(158,57,66)',
        ColorStyle.SUCCESS: 'rgb(65,120,64)',
        ColorStyle.WARNING: 'rgb(143,110,44)',
        ColorStyle.INFO: 'rgb(62,99,153)',
        ColorStyle.HIGHLIGHT: 'rgb(0,3,3)',
        ColorStyle.MAIN: 'rgb(102,102,102)',
        ColorStyle.MUTED: 'rgb(136,139,139)',
        ColorStyle.SEPARATOR: 'rgb(200,200,200)',
        # Todo
        ColorStyle.TODO_COMPLETED: 'rgb(65,120,64)',
        ColorStyle.TODO_IN_PROGRESS: 'rgb(62,99,153)',
        # Tools and agents
        ColorStyle.AGENT_BORDER: 'rgb(205,232,227)',
        # Code
        ColorStyle.DIFF_REMOVED_LINE: 'rgb(0,0,0) on rgb(255,168,180)',
        ColorStyle.DIFF_ADDED_LINE: 'rgb(0,0,0) on rgb(105,219,124)',
        ColorStyle.DIFF_REMOVED_CHAR: 'rgb(0,0,0) on rgb(239,109,119)',
        ColorStyle.DIFF_ADDED_CHAR: 'rgb(0,0,0) on rgb(57,177,78)',
        ColorStyle.CONTEXT_LINE: 'rgb(0,0,0)',
        ColorStyle.INLINE_CODE: 'rgb(109,104,218)',
        # Prompt toolkit
        ColorStyle.INPUT_PLACEHOLDER: 'rgb(136,139,139)',
        ColorStyle.COMPLETION_MENU: 'rgb(154,154,154)',
        ColorStyle.COMPLETION_SELECTED: 'rgb(88,105,247)',
        # Input mode colors
        ColorStyle.BASH_MODE: 'rgb(234,51,134)',
        ColorStyle.MEMORY_MODE: 'rgb(109,104,218)',
        ColorStyle.PLAN_MODE: 'rgb(43,100,101)',
        # Markdown
        ColorStyle.H2: 'rgb(181,75,52)',
    }
)

dark_theme = Theme(
    {
        # AI and user interaction
        ColorStyle.AI_MESSAGE: 'rgb(201,125,92)',
        ColorStyle.AI_THINKING: 'rgb(180,204,245)',
        ColorStyle.CLAUDE: 'rgb(214,119,86)',
        # Status indicators
        ColorStyle.ERROR: 'rgb(237,118,129)',
        ColorStyle.SUCCESS: 'rgb(107,184,109)',
        ColorStyle.WARNING: 'rgb(143,110,44)',
        ColorStyle.INFO: 'rgb(180,204,245)',
        ColorStyle.HIGHLIGHT: 'rgb(255,255,255)',
        ColorStyle.MAIN: 'rgb(210,210,210)',
        ColorStyle.MUTED: 'rgb(151,153,153)',
        ColorStyle.SEPARATOR: 'rgb(50,50,50)',
        # Todo
        ColorStyle.TODO_COMPLETED: 'rgb(107,184,109)',
        ColorStyle.TODO_IN_PROGRESS: 'rgb(150,204,235)',
        # Tools and agents
        ColorStyle.AGENT_BORDER: 'rgb(110,131,127)',
        # Code
        ColorStyle.DIFF_REMOVED_LINE: 'rgb(255,255,255) on rgb(112,47,55)',
        ColorStyle.DIFF_ADDED_LINE: 'rgb(255,255,255) on rgb(49,91,48)',
        ColorStyle.DIFF_REMOVED_CHAR: 'rgb(255,255,255) on rgb(167,95,107)',
        ColorStyle.DIFF_ADDED_CHAR: 'rgb(255,255,255) on rgb(88,164,102)',
        ColorStyle.CONTEXT_LINE: 'rgb(255,255,255)',
        ColorStyle.INLINE_CODE: 'rgb(180,184,245)',
        # Prompt toolkit
        ColorStyle.INPUT_PLACEHOLDER: 'rgb(151,153,153)',
        ColorStyle.COMPLETION_MENU: 'rgb(154,154,154)',
        ColorStyle.COMPLETION_SELECTED: 'rgb(177,185,249)',
        # Input mode colors
        ColorStyle.BASH_MODE: 'rgb(255,102,170)',
        ColorStyle.MEMORY_MODE: 'rgb(200,205,255)',
        ColorStyle.PLAN_MODE: 'rgb(126,184,185)',
        # Markdown
        ColorStyle.H2: 'rgb(221,145,112)',
    }
)
