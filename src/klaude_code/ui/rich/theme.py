from dataclasses import dataclass
from enum import Enum

from rich.style import Style
from rich.theme import Theme


@dataclass
class Palette:
    red: str
    yellow: str
    green: str
    cyan: str
    blue: str
    orange: str
    magenta: str
    grey1: str
    grey2: str
    grey3: str
    grey_green: str
    purple: str
    lavender: str
    diff_add: str
    diff_remove: str
    code_theme: str
    text_background: str


LIGHT_PALETTE = Palette(
    red="red",
    yellow="yellow",
    green="#00875f",
    cyan="cyan",
    blue="#3078C5",
    orange="#d77757",
    magenta="magenta",
    grey1="#667e90",
    grey2="#93a4b1",
    grey3="#c4ced4",
    grey_green="#96a096",
    purple="#5f5fd7",
    lavender="#5f87af",
    diff_add="#2e5a32 on #e8f5e9",
    diff_remove="#5a2e32 on #ffebee",
    code_theme="ansi_light",
    text_background="#e0e0e0",
)

DARK_PALETTE = Palette(
    red="#d75f5f",
    yellow="yellow",
    green="#5fd787",
    cyan="cyan",
    blue="#00afff",
    orange="#e6704e",
    magenta="magenta",
    grey1="#99aabb",
    grey2="#778899",
    grey3="#646464",
    grey_green="#6d8672",
    purple="#afbafe",
    lavender="#9898b8",
    diff_add="#c8e6c9 on #2e4a32",
    diff_remove="#ffcdd2 on #4a2e32",
    code_theme="ansi_dark",
    text_background="#2f3440",
)


class ThemeKey(str, Enum):
    LINES = "lines"
    # DIFF
    DIFF_FILE_NAME = "diff.file_name"
    DIFF_REMOVE = "diff.remove"
    DIFF_ADD = "diff.add"
    DIFF_STATS_ADD = "diff.stats.add"
    DIFF_STATS_REMOVE = "diff.stats.remove"
    # ERROR
    ERROR = "error"
    ERROR_BOLD = "error.bold"
    INTERRUPT = "interrupt"
    # METADATA
    METADATA = "metadata"
    METADATA_DIM = "metadata.dim"
    METADATA_BOLD = "metadata.bold"
    # SPINNER_STATUS
    SPINNER_STATUS = "spinner.status"
    SPINNER_STATUS_TEXT = "spinner.status.text"
    SPINNER_STATUS_TEXT_BOLD = "spinner.status.text.bold"
    # STATUS
    STATUS_HINT = "status.hint"
    # USER_INPUT
    USER_INPUT = "user.input"
    USER_INPUT_PROMPT = "user.input.prompt"
    USER_INPUT_AT_PATTERN = "user.at_pattern"
    USER_INPUT_SLASH_COMMAND = "user.slash_command"
    # REMINDER
    REMINDER = "reminder"
    REMINDER_BOLD = "reminder.bold"
    # TOOL
    INVALID_TOOL_CALL_ARGS = "tool.invalid_tool_call_args"
    TOOL_NAME = "tool.name"
    TOOL_PARAM_FILE_PATH = "tool.param.file_path"
    TOOL_PARAM = "tool.param"
    TOOL_PARAM_BOLD = "tool.param.bold"
    TOOL_RESULT = "tool.result"
    TOOL_RESULT_TRUNCATED = "tool.result.truncated"
    TOOL_RESULT_BOLD = "tool.result.bold"
    TOOL_MARK = "tool.mark"
    TOOL_APPROVED = "tool.approved"
    TOOL_REJECTED = "tool.rejected"
    TOOL_TIMEOUT = "tool.timeout"
    # THINKING
    THINKING = "thinking"
    THINKING_BOLD = "thinking.bold"
    # TODO_ITEM
    TODO_EXPLANATION = "todo.explanation"
    TODO_PENDING_MARK = "todo.pending.mark"
    TODO_COMPLETED_MARK = "todo.completed.mark"
    TODO_IN_PROGRESS_MARK = "todo.in_progress.mark"
    TODO_NEW_COMPLETED_MARK = "todo.new_completed.mark"
    TODO_PENDING = "todo.pending"
    TODO_COMPLETED = "todo.completed"
    TODO_IN_PROGRESS = "todo.in_progress"
    TODO_NEW_COMPLETED = "todo.new_completed"
    # WELCOME
    WELCOME_HIGHLIGHT_BOLD = "welcome.highlight.bold"
    WELCOME_HIGHLIGHT = "welcome.highlight"
    WELCOME_INFO = "welcome.info"
    # WELCOME DEBUG
    WELCOME_DEBUG_TITLE = "welcome.debug.title"
    WELCOME_DEBUG_BORDER = "welcome.debug.border"
    # RESUME
    RESUME_FLAG = "resume.flag"
    RESUME_INFO = "resume.info"
    # CONFIGURATION DISPLAY
    CONFIG_TABLE_HEADER = "config.table.header"
    CONFIG_STATUS_OK = "config.status.ok"
    CONFIG_STATUS_PRIMARY = "config.status.primary"
    CONFIG_STATUS_ERROR = "config.status.error"
    CONFIG_ITEM_NAME = "config.item.name"
    CONFIG_PARAM_LABEL = "config.param.label"
    CONFIG_PANEL_BORDER = "config.panel.border"

    def __str__(self) -> str:
        return self.value


@dataclass
class Themes:
    app_theme: Theme
    markdown_theme: Theme
    thinking_markdown_theme: Theme
    code_theme: str
    sub_agent_colors: list[Style]


def get_theme(theme: str | None = None) -> Themes:
    palette = LIGHT_PALETTE if theme == "light" else DARK_PALETTE
    return Themes(
        app_theme=Theme(
            styles={
                ThemeKey.LINES.value: palette.grey3,
                # DIFF
                ThemeKey.DIFF_FILE_NAME.value: palette.blue,
                ThemeKey.DIFF_REMOVE.value: palette.diff_remove,
                ThemeKey.DIFF_ADD.value: palette.diff_add,
                ThemeKey.DIFF_STATS_ADD.value: palette.green,
                ThemeKey.DIFF_STATS_REMOVE.value: palette.red,
                # ERROR
                ThemeKey.ERROR.value: palette.red,
                ThemeKey.ERROR_BOLD.value: "bold " + palette.red,
                ThemeKey.INTERRUPT.value: "reverse bold " + palette.red,
                # USER_INPUT
                ThemeKey.USER_INPUT.value: palette.magenta,
                ThemeKey.USER_INPUT_PROMPT.value: palette.magenta,
                ThemeKey.USER_INPUT_AT_PATTERN.value: palette.purple,
                ThemeKey.USER_INPUT_SLASH_COMMAND.value: "bold reverse " + palette.blue,
                # METADATA
                ThemeKey.METADATA.value: palette.lavender,
                ThemeKey.METADATA_DIM.value: "dim " + palette.lavender,
                ThemeKey.METADATA_BOLD.value: "bold " + palette.lavender,
                # SPINNER_STATUS
                ThemeKey.SPINNER_STATUS.value: palette.blue,
                ThemeKey.SPINNER_STATUS_TEXT.value: palette.blue,
                ThemeKey.SPINNER_STATUS_TEXT_BOLD.value: "bold " + palette.blue,
                # STATUS
                ThemeKey.STATUS_HINT.value: palette.grey2,
                # REMINDER
                ThemeKey.REMINDER.value: palette.grey1,
                ThemeKey.REMINDER_BOLD.value: "bold " + palette.grey1,
                # TOOL
                ThemeKey.INVALID_TOOL_CALL_ARGS.value: palette.yellow,
                ThemeKey.TOOL_NAME.value: "bold",
                ThemeKey.TOOL_PARAM_FILE_PATH.value: palette.green,
                ThemeKey.TOOL_PARAM.value: palette.green,
                ThemeKey.TOOL_PARAM_BOLD.value: "bold " + palette.green,
                ThemeKey.TOOL_RESULT.value: palette.grey_green,
                ThemeKey.TOOL_RESULT_BOLD.value: "bold " + palette.grey_green,
                ThemeKey.TOOL_RESULT_TRUNCATED.value: palette.yellow,
                ThemeKey.TOOL_MARK.value: "bold",
                ThemeKey.TOOL_APPROVED.value: palette.green + " bold reverse",
                ThemeKey.TOOL_REJECTED.value: palette.red + " bold reverse",
                ThemeKey.TOOL_TIMEOUT.value: palette.yellow,
                # THINKING
                ThemeKey.THINKING.value: "italic " + palette.grey2,
                ThemeKey.THINKING_BOLD.value: "bold italic " + palette.grey1,
                # TODO_ITEM
                ThemeKey.TODO_EXPLANATION.value: palette.grey1 + " italic",
                ThemeKey.TODO_PENDING_MARK.value: "bold " + palette.grey1,
                ThemeKey.TODO_COMPLETED_MARK.value: "bold " + palette.grey3,
                ThemeKey.TODO_IN_PROGRESS_MARK.value: "bold " + palette.blue,
                ThemeKey.TODO_NEW_COMPLETED_MARK.value: "bold " + palette.green,
                ThemeKey.TODO_PENDING.value: palette.grey1,
                ThemeKey.TODO_COMPLETED.value: palette.grey3 + " strike",
                ThemeKey.TODO_IN_PROGRESS.value: "bold " + palette.blue,
                ThemeKey.TODO_NEW_COMPLETED.value: "bold strike " + palette.green,
                # WELCOME
                ThemeKey.WELCOME_HIGHLIGHT_BOLD.value: "bold",
                ThemeKey.WELCOME_HIGHLIGHT.value: palette.blue,
                ThemeKey.WELCOME_INFO.value: palette.grey1,
                # WELCOME DEBUG
                ThemeKey.WELCOME_DEBUG_TITLE.value: "bold " + palette.red,
                ThemeKey.WELCOME_DEBUG_BORDER.value: palette.red,
                # RESUME
                ThemeKey.RESUME_FLAG.value: "bold reverse " + palette.green,
                ThemeKey.RESUME_INFO.value: palette.green,
                # CONFIGURATION DISPLAY
                ThemeKey.CONFIG_TABLE_HEADER.value: palette.green,
                ThemeKey.CONFIG_STATUS_OK.value: palette.green,
                ThemeKey.CONFIG_STATUS_PRIMARY.value: palette.yellow,
                ThemeKey.CONFIG_STATUS_ERROR.value: palette.red,
                ThemeKey.CONFIG_ITEM_NAME.value: palette.cyan,
                ThemeKey.CONFIG_PARAM_LABEL.value: palette.grey1,
                ThemeKey.CONFIG_PANEL_BORDER.value: palette.grey3,
            }
        ),
        markdown_theme=Theme(
            styles={
                "markdown.code": palette.purple,
                "markdown.code.border": palette.grey3,
                "markdown.h1": "bold reverse",
                "markdown.h1.border": palette.grey3,
                "markdown.h2.border": palette.grey3,
                "markdown.h3": "bold " + palette.grey1,
                "markdown.h4": "bold " + palette.grey2,
                "markdown.hr": palette.grey3,
                "markdown.item.bullet": palette.grey2,
                "markdown.item.number": palette.grey2,
                "markdown.link": "underline " + palette.blue,
                "markdown.link_url": "underline " + palette.blue,
            }
        ),
        thinking_markdown_theme=Theme(
            styles={
                "markdown.code": palette.grey1 + " italic on " + palette.text_background,
                "markdown.code.block": palette.grey1,
                "markdown.code.border": palette.grey3,
                "markdown.h1": "bold reverse",
                "markdown.h1.border": palette.grey3,
                "markdown.h2.border": palette.grey3,
                "markdown.h3": "bold " + palette.grey1,
                "markdown.h4": "bold " + palette.grey2,
                "markdown.hr": palette.grey3,
                "markdown.item.bullet": palette.grey2,
                "markdown.item.number": palette.grey2,
                "markdown.link": "underline " + palette.blue,
                "markdown.link_url": "underline " + palette.blue,
                "markdown.strong": "bold italic " + palette.grey1,
            }
        ),
        code_theme=palette.code_theme,
        sub_agent_colors=[
            Style(color=palette.cyan),
            Style(color=palette.green),
            Style(color=palette.blue),
            Style(color=palette.purple),
            Style(color=palette.orange),
            Style(color=palette.red),
            Style(color=palette.grey1),
            Style(color=palette.yellow),
        ],
    )
