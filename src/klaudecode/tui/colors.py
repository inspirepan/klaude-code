from enum import Enum, auto

from rich.style import Style
from rich.theme import Theme

"""
Color theme system supporting four themes:
- light: RGB-based light theme with precise color definitions
- dark: RGB-based dark theme with precise color definitions  
- light_ansi: ANSI color fallback for light theme (for terminal compatibility)
- dark_ansi: ANSI color fallback for dark theme (for terminal compatibility)
"""


class ColorStyle(str, Enum):
    # AI
    AI_CONTENT = 'ai_content'
    AI_THINKING = 'ai_thinking'
    CLAUDE = 'claude'
    # Status
    ERROR = 'error'
    SUCCESS = 'success'
    WARNING = 'warning'
    INFO = 'info'
    # Text
    HIGHLIGHT = 'highlight'
    MAIN = 'main'
    HINT = 'hint'
    # Border and Separator
    LINE = 'line'
    # Todos
    TODO_COMPLETED = 'todo_completed'
    TODO_IN_PROGRESS = 'todo_in_progress'
    # Tools
    TOOL_NAME = 'tool_name'
    # Code
    DIFF_REMOVED_LINE = 'diff_removed_line'
    DIFF_ADDED_LINE = 'diff_added_line'
    DIFF_REMOVED_CHAR = 'diff_removed_char'
    DIFF_ADDED_CHAR = 'diff_added_char'
    CONTEXT_LINE = 'context_line'
    # User Input Colors
    INPUT_PLACEHOLDER = 'input_placeholder'
    COMPLETION_MENU = 'completion_menu'
    COMPLETION_SELECTED = 'completion_selected'
    # Input Mode Colors
    BASH_MODE = 'bash_mode'
    MEMORY_MODE = 'memory_mode'
    PLAN_MODE = 'plan_mode'
    # Markdown
    HEADER_2 = 'header_2'
    HEADER_3 = 'header_3'

    INLINE_CODE = 'inline_code'

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

    @property
    def style(self) -> Style:
        # Import here to avoid circular import
        from .console import console

        return console.console.get_style(self.value)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class ThemeColorEnum(Enum):
    CLAUDE = auto()
    RED = auto()
    GREEN = auto()
    BLUE = auto()
    YELLOW = auto()
    PURPLE = auto()
    CYAN = auto()
    MAGENTA = auto()
    DIFF_REMOVED_LINE = auto()
    DIFF_ADDED_LINE = auto()
    DIFF_REMOVED_CHAR = auto()
    DIFF_ADDED_CHAR = auto()
    HIGHLIGHT = auto()
    PRIMARY = auto()
    SECONDARY = auto()
    TERTIARY = auto()
    QUATERNARY = auto()


light_theme_colors = {
    ThemeColorEnum.CLAUDE: 'rgb(214,119,86)',
    ThemeColorEnum.RED: 'rgb(158,57,66)',
    ThemeColorEnum.GREEN: 'rgb(65,120,64)',
    ThemeColorEnum.BLUE: 'rgb(56,120,183)',
    ThemeColorEnum.YELLOW: 'rgb(143,110,44)',
    ThemeColorEnum.PURPLE: 'rgb(88,105,247)',
    ThemeColorEnum.CYAN: 'rgb(43,100,101)',
    ThemeColorEnum.MAGENTA: 'rgb(234,51,134)',
    ThemeColorEnum.DIFF_REMOVED_LINE: 'rgb(0,0,0) on rgb(255,168,180)',
    ThemeColorEnum.DIFF_ADDED_LINE: 'rgb(0,0,0) on rgb(105,219,124)',
    ThemeColorEnum.DIFF_REMOVED_CHAR: 'rgb(0,0,0) on rgb(239,109,119)',
    ThemeColorEnum.DIFF_ADDED_CHAR: 'rgb(0,0,0) on rgb(57,177,78)',
    ThemeColorEnum.HIGHLIGHT: 'rgb(0,0,0)',
    ThemeColorEnum.PRIMARY: 'rgb(66,66,66)',
    ThemeColorEnum.SECONDARY: 'rgb(96,96,96)',
    ThemeColorEnum.TERTIARY: 'rgb(136,139,139)',
    ThemeColorEnum.QUATERNARY: 'rgb(200,200,200)',
}

dark_theme_colors = {
    ThemeColorEnum.CLAUDE: 'rgb(214,119,86)',
    ThemeColorEnum.RED: 'rgb(237,118,129)',
    ThemeColorEnum.GREEN: 'rgb(107,184,109)',
    ThemeColorEnum.BLUE: 'rgb(180,204,245)',
    ThemeColorEnum.YELLOW: 'rgb(183,150,94)',
    ThemeColorEnum.PURPLE: 'rgb(180,184,245)',
    ThemeColorEnum.CYAN: 'rgb(126,184,185)',
    ThemeColorEnum.MAGENTA: 'rgb(254,71,144)',
    ThemeColorEnum.DIFF_REMOVED_LINE: 'rgb(255,255,255) on rgb(112,47,55)',
    ThemeColorEnum.DIFF_ADDED_LINE: 'rgb(255,255,255) on rgb(49,91,48)',
    ThemeColorEnum.DIFF_REMOVED_CHAR: 'rgb(255,255,255) on rgb(167,95,107)',
    ThemeColorEnum.DIFF_ADDED_CHAR: 'rgb(255,255,255) on rgb(88,164,102)',
    ThemeColorEnum.HIGHLIGHT: 'rgb(255,255,255)',
    ThemeColorEnum.PRIMARY: 'rgb(230,230,230)',
    ThemeColorEnum.SECONDARY: 'rgb(200,200,200)',
    ThemeColorEnum.TERTIARY: 'rgb(151,153,153)',
    ThemeColorEnum.QUATERNARY: 'rgb(100,100,100)',
}

light_ansi_theme_colors = {
    ThemeColorEnum.CLAUDE: 'yellow',
    ThemeColorEnum.RED: 'red',
    ThemeColorEnum.GREEN: 'green',
    ThemeColorEnum.BLUE: 'blue',
    ThemeColorEnum.YELLOW: 'yellow',
    ThemeColorEnum.PURPLE: 'magenta',
    ThemeColorEnum.CYAN: 'cyan',
    ThemeColorEnum.MAGENTA: 'magenta',
    ThemeColorEnum.DIFF_REMOVED_LINE: 'black on bright_red',
    ThemeColorEnum.DIFF_ADDED_LINE: 'black on bright_green',
    ThemeColorEnum.DIFF_REMOVED_CHAR: 'black on red',
    ThemeColorEnum.DIFF_ADDED_CHAR: 'black on green',
    ThemeColorEnum.HIGHLIGHT: 'black',
    ThemeColorEnum.PRIMARY: 'black',
    ThemeColorEnum.SECONDARY: 'bright_black',
    ThemeColorEnum.TERTIARY: 'bright_black',
    ThemeColorEnum.QUATERNARY: 'bright_black',
}


dark_ansi_theme_colors = {
    ThemeColorEnum.CLAUDE: 'bright_yellow',
    ThemeColorEnum.RED: 'bright_red',
    ThemeColorEnum.GREEN: 'bright_green',
    ThemeColorEnum.BLUE: 'bright_blue',
    ThemeColorEnum.YELLOW: 'bright_yellow',
    ThemeColorEnum.PURPLE: 'bright_magenta',
    ThemeColorEnum.CYAN: 'bright_cyan',
    ThemeColorEnum.MAGENTA: 'bright_magenta',
    ThemeColorEnum.DIFF_REMOVED_LINE: 'bright_white on bright_red',
    ThemeColorEnum.DIFF_ADDED_LINE: 'bright_white on bright_green',
    ThemeColorEnum.DIFF_REMOVED_CHAR: 'bright_white on red',
    ThemeColorEnum.DIFF_ADDED_CHAR: 'bright_white on green',
    ThemeColorEnum.HIGHLIGHT: 'bright_white',
    ThemeColorEnum.PRIMARY: 'bright_white',
    ThemeColorEnum.SECONDARY: 'white',
    ThemeColorEnum.TERTIARY: 'bright_black',
    ThemeColorEnum.QUATERNARY: 'bright_black',
}

theme_map = {
    'light': light_theme_colors,
    'dark': dark_theme_colors,
    'light_ansi': light_ansi_theme_colors,
    'dark_ansi': dark_ansi_theme_colors,
}


def get_theme(theme: str) -> Theme:
    theme_colors = theme_map.get(theme, dark_theme_colors)

    return Theme(
        {
            # AI and user interaction
            ColorStyle.AI_CONTENT: theme_colors[ThemeColorEnum.PRIMARY],
            ColorStyle.AI_THINKING: theme_colors[ThemeColorEnum.TERTIARY],
            ColorStyle.CLAUDE: theme_colors[ThemeColorEnum.CLAUDE],
            # Status indicators
            ColorStyle.ERROR: theme_colors[ThemeColorEnum.RED],
            ColorStyle.SUCCESS: theme_colors[ThemeColorEnum.GREEN],
            ColorStyle.WARNING: theme_colors[ThemeColorEnum.YELLOW],
            ColorStyle.INFO: theme_colors[ThemeColorEnum.BLUE],
            # Text
            ColorStyle.HIGHLIGHT: theme_colors[ThemeColorEnum.HIGHLIGHT],
            ColorStyle.MAIN: theme_colors[ThemeColorEnum.SECONDARY],
            ColorStyle.HINT: theme_colors[ThemeColorEnum.TERTIARY],
            # Border and Separator
            ColorStyle.LINE: theme_colors[ThemeColorEnum.QUATERNARY],
            # Todo
            ColorStyle.TODO_COMPLETED: theme_colors[ThemeColorEnum.GREEN],
            ColorStyle.TODO_IN_PROGRESS: theme_colors[ThemeColorEnum.BLUE],
            # Tools
            ColorStyle.TOOL_NAME: theme_colors[ThemeColorEnum.PRIMARY],
            # Code
            ColorStyle.DIFF_REMOVED_LINE: theme_colors[ThemeColorEnum.DIFF_REMOVED_LINE],
            ColorStyle.DIFF_ADDED_LINE: theme_colors[ThemeColorEnum.DIFF_ADDED_LINE],
            ColorStyle.DIFF_REMOVED_CHAR: theme_colors[ThemeColorEnum.DIFF_REMOVED_CHAR],
            ColorStyle.DIFF_ADDED_CHAR: theme_colors[ThemeColorEnum.DIFF_ADDED_CHAR],
            ColorStyle.CONTEXT_LINE: theme_colors[ThemeColorEnum.SECONDARY],
            # User Input Colors
            ColorStyle.INPUT_PLACEHOLDER: theme_colors[ThemeColorEnum.TERTIARY],
            ColorStyle.COMPLETION_MENU: theme_colors[ThemeColorEnum.TERTIARY],
            ColorStyle.COMPLETION_SELECTED: theme_colors[ThemeColorEnum.PURPLE],
            # Input Mode Colors
            ColorStyle.BASH_MODE: theme_colors[ThemeColorEnum.MAGENTA],
            ColorStyle.MEMORY_MODE: theme_colors[ThemeColorEnum.PURPLE],
            ColorStyle.PLAN_MODE: theme_colors[ThemeColorEnum.CYAN],
            # Markdown
            ColorStyle.INLINE_CODE: theme_colors[ThemeColorEnum.PURPLE],
            ColorStyle.HEADER_2: theme_colors[ThemeColorEnum.HIGHLIGHT],
            ColorStyle.HEADER_3: theme_colors[ThemeColorEnum.PRIMARY],
        }
    )
