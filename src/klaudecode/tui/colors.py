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
    CLAUDE = auto()

    # Messages
    AI_CONTENT = auto()
    AI_THINKING = auto()
    AI_MARK = auto()
    TOOL_NAME = auto()
    USER_MESSAGE = auto()

    # Markdown
    HEADER_1 = auto()
    HEADER_2 = auto()
    HEADER_3 = auto()
    HEADER_4 = auto()
    INLINE_CODE = auto()

    # Status
    STATUS = auto()
    ERROR = auto()
    SUCCESS = auto()
    WARNING = auto()
    INFO = auto()

    # Basic
    HIGHLIGHT = auto()
    MAIN = auto()
    HINT = auto()
    LINE = auto()

    # Todos
    TODO_COMPLETED = auto()
    TODO_IN_PROGRESS = auto()

    # Diff
    DIFF_REMOVED_LINE = auto()
    DIFF_ADDED_LINE = auto()
    DIFF_REMOVED_CHAR = auto()
    DIFF_ADDED_CHAR = auto()
    CONTEXT_LINE = auto()

    # User Input
    INPUT_PLACEHOLDER = auto()
    COMPLETION_MENU = auto()
    COMPLETION_SELECTED = auto()

    # Input Mode
    BASH_MODE = auto()
    MEMORY_MODE = auto()
    PLAN_MODE = auto()

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
    ThemeColorEnum.CLAUDE: '#de7356',
    ThemeColorEnum.RED: '#ab2c3f',
    ThemeColorEnum.GREEN: '#2b7a3a',
    ThemeColorEnum.BLUE: '#3678b7',
    ThemeColorEnum.YELLOW: '#a56416',
    ThemeColorEnum.PURPLE: '#5869f7',
    ThemeColorEnum.CYAN: '#006666',
    ThemeColorEnum.MAGENTA: '#a80059',
    ThemeColorEnum.DIFF_REMOVED_LINE: '#000000 on #ffa8b4',
    ThemeColorEnum.DIFF_ADDED_LINE: '#000000 on #69db7c',
    ThemeColorEnum.DIFF_REMOVED_CHAR: '#000000 on #ef6d77',
    ThemeColorEnum.DIFF_ADDED_CHAR: '#000000 on #39b14e',
    ThemeColorEnum.HIGHLIGHT: '#000000',
    ThemeColorEnum.PRIMARY: '#3d3929',
    ThemeColorEnum.SECONDARY: '#6d6959',
    ThemeColorEnum.TERTIARY: '#8d8979',
    ThemeColorEnum.QUATERNARY: '#bdb9a9',
}


light_claude_theme_colors = {
    **light_theme_colors,
    ColorStyle.AI_CONTENT: '#bd5d3a',
    ColorStyle.AI_MARK: '#bd5d3a',
    ColorStyle.HEADER_1: '#9d3d1a',
    ColorStyle.HEADER_2: '#9d3d1a',
    ColorStyle.HEADER_3: '#9d3d1a',
    ColorStyle.HEADER_4: '#9d3d1a',
}


dark_theme_colors = {
    ThemeColorEnum.CLAUDE: '#e6704e',
    ThemeColorEnum.RED: '#ff5e7d',
    ThemeColorEnum.GREEN: '#00bd5a',
    ThemeColorEnum.BLUE: '#53b1ff',
    ThemeColorEnum.YELLOW: '#ece100',
    ThemeColorEnum.PURPLE: '#afbafe',
    ThemeColorEnum.CYAN: '#38b9ac',
    ThemeColorEnum.MAGENTA: '#ff4cb4',
    ThemeColorEnum.DIFF_REMOVED_LINE: '#ffffff on #702f37',
    ThemeColorEnum.DIFF_ADDED_LINE: '#ffffff on #005e24',
    ThemeColorEnum.DIFF_REMOVED_CHAR: '#ffffff on #c1526b',
    ThemeColorEnum.DIFF_ADDED_CHAR: '#ffffff on #00a958',
    ThemeColorEnum.HIGHLIGHT: '#ffffff',
    ThemeColorEnum.PRIMARY: '#e6e6e6',
    ThemeColorEnum.SECONDARY: '#c8c8c8',
    ThemeColorEnum.TERTIARY: '#979999',
    ThemeColorEnum.QUATERNARY: '#646464',
}


dark_claude_theme_colors = {
    **dark_theme_colors,
    ColorStyle.AI_CONTENT: '#e89981',
    ColorStyle.AI_MARK: '#e89981',
    ColorStyle.HEADER_1: '#e89981',
    ColorStyle.HEADER_2: '#e89981',
    ColorStyle.HEADER_3: '#e89981',
    ColorStyle.HEADER_4: '#e89981',
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
    ThemeColorEnum.DIFF_REMOVED_LINE: 'black on red',
    ThemeColorEnum.DIFF_ADDED_LINE: 'black on green',
    ThemeColorEnum.DIFF_REMOVED_CHAR: 'black on bright_red',
    ThemeColorEnum.DIFF_ADDED_CHAR: 'black on bright_green',
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
    'light_claude': light_claude_theme_colors,
    'dark_claude': dark_claude_theme_colors,
}


def get_all_themes() -> list[str]:
    return list(theme_map.keys())


def get_theme(theme: str) -> Theme:
    theme_colors = theme_map.get(theme, dark_theme_colors)

    return Theme(
        {
            ColorStyle.CLAUDE: theme_colors[ThemeColorEnum.CLAUDE],
            # Messages
            ColorStyle.AI_CONTENT: theme_colors.get(ColorStyle.AI_CONTENT, theme_colors[ThemeColorEnum.PRIMARY]),
            ColorStyle.AI_THINKING: theme_colors.get(ColorStyle.AI_THINKING, theme_colors[ThemeColorEnum.TERTIARY]),
            ColorStyle.AI_MARK: theme_colors.get(ColorStyle.AI_MARK, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.TOOL_NAME: theme_colors.get(ColorStyle.TOOL_NAME, theme_colors[ThemeColorEnum.PRIMARY]),
            ColorStyle.USER_MESSAGE: theme_colors.get(ColorStyle.USER_MESSAGE, theme_colors[ThemeColorEnum.SECONDARY]),
            # Markdown
            ColorStyle.HEADER_1: theme_colors.get(ColorStyle.HEADER_1, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.HEADER_2: theme_colors.get(ColorStyle.HEADER_2, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.HEADER_3: theme_colors.get(ColorStyle.HEADER_3, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.HEADER_4: theme_colors.get(ColorStyle.HEADER_4, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.INLINE_CODE: theme_colors.get(ColorStyle.INLINE_CODE, theme_colors[ThemeColorEnum.PURPLE]),
            # Status
            ColorStyle.STATUS: theme_colors.get(ColorStyle.STATUS, theme_colors[ThemeColorEnum.CLAUDE]),
            ColorStyle.ERROR: theme_colors.get(ColorStyle.ERROR, theme_colors[ThemeColorEnum.RED]),
            ColorStyle.SUCCESS: theme_colors.get(ColorStyle.SUCCESS, theme_colors[ThemeColorEnum.GREEN]),
            ColorStyle.WARNING: theme_colors.get(ColorStyle.WARNING, theme_colors[ThemeColorEnum.YELLOW]),
            ColorStyle.INFO: theme_colors.get(ColorStyle.INFO, theme_colors[ThemeColorEnum.BLUE]),
            # Basic
            ColorStyle.HIGHLIGHT: theme_colors.get(ColorStyle.HIGHLIGHT, theme_colors[ThemeColorEnum.HIGHLIGHT]),
            ColorStyle.MAIN: theme_colors.get(ColorStyle.MAIN, theme_colors[ThemeColorEnum.SECONDARY]),
            ColorStyle.HINT: theme_colors.get(ColorStyle.HINT, theme_colors[ThemeColorEnum.TERTIARY]),
            ColorStyle.LINE: theme_colors.get(ColorStyle.LINE, theme_colors[ThemeColorEnum.QUATERNARY]),
            # Todos
            ColorStyle.TODO_COMPLETED: theme_colors.get(ColorStyle.TODO_COMPLETED, theme_colors[ThemeColorEnum.GREEN]),
            ColorStyle.TODO_IN_PROGRESS: theme_colors.get(ColorStyle.TODO_IN_PROGRESS, theme_colors[ThemeColorEnum.BLUE]),
            # Diff
            ColorStyle.DIFF_REMOVED_LINE: theme_colors[ThemeColorEnum.DIFF_REMOVED_LINE],
            ColorStyle.DIFF_ADDED_LINE: theme_colors[ThemeColorEnum.DIFF_ADDED_LINE],
            ColorStyle.DIFF_REMOVED_CHAR: theme_colors[ThemeColorEnum.DIFF_REMOVED_CHAR],
            ColorStyle.DIFF_ADDED_CHAR: theme_colors[ThemeColorEnum.DIFF_ADDED_CHAR],
            ColorStyle.CONTEXT_LINE: theme_colors.get(ColorStyle.CONTEXT_LINE, theme_colors[ThemeColorEnum.SECONDARY]),
            # User Input
            ColorStyle.INPUT_PLACEHOLDER: theme_colors.get(ColorStyle.INPUT_PLACEHOLDER, theme_colors[ThemeColorEnum.TERTIARY]),
            ColorStyle.COMPLETION_MENU: theme_colors.get(ColorStyle.COMPLETION_MENU, theme_colors[ThemeColorEnum.TERTIARY]),
            ColorStyle.COMPLETION_SELECTED: theme_colors.get(ColorStyle.COMPLETION_SELECTED, theme_colors[ThemeColorEnum.PURPLE]),
            # Input Mode
            ColorStyle.BASH_MODE: theme_colors.get(ColorStyle.BASH_MODE, theme_colors[ThemeColorEnum.MAGENTA]),
            ColorStyle.MEMORY_MODE: theme_colors.get(ColorStyle.MEMORY_MODE, theme_colors[ThemeColorEnum.PURPLE]),
            ColorStyle.PLAN_MODE: theme_colors.get(ColorStyle.PLAN_MODE, theme_colors[ThemeColorEnum.CYAN]),
        }
    )
