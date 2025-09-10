from dataclasses import dataclass
from enum import Enum

from rich.theme import Theme


@dataclass
class Palette:
    red: str
    yellow: str
    green: str
    cyan: str
    blue: str
    orange: str
    grey_blue: str
    grey1: str
    grey2: str
    grey3: str
    purple: str
    diff_add: str
    diff_remove: str
    code_theme: str


LIGHT_PALETTE = Palette(
    red="red",
    yellow="yellow",
    green="green",
    cyan="cyan",
    blue="dodger_blue1",
    orange="#de7356",
    grey_blue="steel_blue",
    grey1="dim",
    grey2="grey50",
    grey3="grey70",
    purple="medium_purple3",
    diff_add="#333333 on #69db7c",
    diff_remove="#333333 on #ffa8b4",
    code_theme="solarized-light",
)

DARK_PALETTE = Palette(
    red="red",
    yellow="yellow",
    green="sea_green3",
    cyan="cyan",
    blue="dodger_blue1",
    orange="#e6704e",
    grey_blue="steel_blue",
    grey1="gray70",
    grey2="gray58",
    grey3="gray30",
    purple="light_steel_blue",
    diff_add="#ffffff on #005e24",
    diff_remove="#ffffff on #702f37",
    code_theme="github-dark",
)


class ThemeKey(str, Enum):
    LINES = "lines"
    # DIFF
    DIFF_REMOVE = "diff.remove"
    DIFF_ADD = "diff.add"
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
    SPINNER_STATUS_BOLD = "spinner.status.bold"
    # USER_INPUT
    USER_INPUT = "user.input"
    USER_INPUT_DIM = "user.input.dim"
    USER_INPUT_AT_PATTERN = "user.at_pattern"
    USER_INPUT_SLASH_COMMAND = "user.slash_command"
    # REMINDER
    REMINDER = "reminder"
    REMINDER_BOLD = "reminder.bold"
    REMINDER_DIM = "reminder.dim"
    # TOOL
    INVALID_TOOL_CALL_ARGS = "tool.invalid_tool_call_args"
    TOOL_NAME = "tool.name"
    TOOL_PARAM_FILE_PATH = "tool.param.file_path"
    TOOL_PARAM = "tool.param"
    TOOL_PARAM_BOLD = "tool.param.bold"
    TOOL_RESULT = "tool.result"
    TOOL_MARK = "tool.mark"
    TOOL_APPROVED = "tool.approved"
    TOOL_REJECTED = "tool.rejected"
    # THINKING
    THINKING = "thinking"
    THINKING_BOLD = "thinking.bold"
    # TODO_ITEM
    TODO_PENDING_MARK = "todo.pending.mark"
    TODO_COMPLETED_MARK = "todo.completed.mark"
    TODO_IN_PROGRESS_MARK = "todo.in_progress.mark"
    TODO_NEW_COMPLETED_MARK = "todo.new_completed.mark"
    TODO_PENDING = "todo.pending"
    TODO_COMPLETED = "todo.completed"
    TODO_IN_PROGRESS = "todo.in_progress"
    TODO_NEW_COMPLETED = "todo.new_completed"
    # WELCOME
    WELCOME_HIGHLIGHT = "welcome.highlight"
    WELCOME_INFO = "welcome.info"
    # RESUME
    RESUME_FLAG = "resume.flag"
    RESUME_INFO = "resume.info"
    # ANNOTATION
    ANNOTATION_URL = "annotation.url"
    ANNOTATION_URL_HIGHLIGHT = "annotation.url.highlight"
    ANNOTATION_SEARCH_CONTENT = "annotation.search_content"
    # PALETTE COLORS - Direct palette passthrough
    RED = "r"
    YELLOW = "y"
    GREEN = "g"
    CYAN = "c"
    BLUE = "b"
    ORANGE = "o"
    GREY_BLUE = "grey_blue"
    GREY1 = "grey1"
    GREY2 = "grey2"
    GREY3 = "grey3"
    PURPLE = "p"

    def __str__(self) -> str:
        return self.value


@dataclass
class Themes:
    app_theme: Theme
    markdown_theme: Theme
    code_theme: str
    sub_agent_colors: list[ThemeKey]


def get_theme(theme: str | None = None) -> Themes:
    if theme == "light":
        palette = LIGHT_PALETTE
    else:
        palette = DARK_PALETTE
    return Themes(
        app_theme=Theme(
            styles={
                ThemeKey.LINES.value: palette.grey3,
                # DIFF
                ThemeKey.DIFF_REMOVE.value: palette.diff_remove,
                ThemeKey.DIFF_ADD.value: palette.diff_add,
                # ERROR
                ThemeKey.ERROR.value: palette.red,
                ThemeKey.ERROR_BOLD.value: "bold " + palette.red,
                ThemeKey.INTERRUPT.value: "reverse bold " + palette.red,
                # USER_INPUT
                ThemeKey.USER_INPUT.value: palette.cyan,
                ThemeKey.USER_INPUT_DIM.value: palette.cyan + " dim",
                ThemeKey.USER_INPUT_AT_PATTERN.value: "reverse " + palette.purple,
                ThemeKey.USER_INPUT_SLASH_COMMAND.value: "reverse bold " + palette.cyan,
                # METADATA
                ThemeKey.METADATA.value: palette.grey_blue,
                ThemeKey.METADATA_DIM.value: "dim " + palette.grey_blue,
                ThemeKey.METADATA_BOLD.value: "bold " + palette.grey_blue,
                # SPINNER_STATUS
                ThemeKey.SPINNER_STATUS.value: palette.blue,
                ThemeKey.SPINNER_STATUS_BOLD.value: "bold " + palette.blue,
                # REMINDER
                ThemeKey.REMINDER.value: palette.purple,
                ThemeKey.REMINDER_BOLD.value: "bold " + palette.purple,
                ThemeKey.REMINDER_DIM.value: "dim " + palette.purple,
                # TOOL
                ThemeKey.INVALID_TOOL_CALL_ARGS.value: palette.yellow,
                ThemeKey.TOOL_NAME.value: "bold",
                ThemeKey.TOOL_PARAM_FILE_PATH.value: palette.green,
                ThemeKey.TOOL_PARAM.value: palette.green,
                ThemeKey.TOOL_PARAM_BOLD.value: "bold " + palette.green,
                ThemeKey.TOOL_RESULT.value: palette.grey2,
                ThemeKey.TOOL_MARK.value: "bold",
                ThemeKey.TOOL_APPROVED.value: palette.green + " bold reverse",
                ThemeKey.TOOL_REJECTED.value: palette.red + " bold reverse",
                # THINKING
                ThemeKey.THINKING.value: "italic " + palette.grey1,
                ThemeKey.THINKING_BOLD.value: "bold italic " + palette.grey1,
                # TODO_ITEM
                ThemeKey.TODO_PENDING_MARK.value: "bold " + palette.grey1,
                ThemeKey.TODO_COMPLETED_MARK.value: "bold " + palette.grey1,
                ThemeKey.TODO_IN_PROGRESS_MARK.value: "bold " + palette.blue,
                ThemeKey.TODO_NEW_COMPLETED_MARK.value: "bold " + palette.green,
                ThemeKey.TODO_PENDING.value: palette.grey1,
                ThemeKey.TODO_COMPLETED.value: palette.grey1 + " strike",
                ThemeKey.TODO_IN_PROGRESS.value: "bold " + palette.blue,
                ThemeKey.TODO_NEW_COMPLETED.value: "bold strike " + palette.green,
                # WELCOME
                ThemeKey.WELCOME_HIGHLIGHT.value: "bold",
                ThemeKey.WELCOME_INFO.value: palette.grey1,
                # RESUME
                ThemeKey.RESUME_FLAG.value: "bold reverse " + palette.green,
                ThemeKey.RESUME_INFO.value: palette.green,
                # URL
                ThemeKey.ANNOTATION_URL.value: palette.blue,
                ThemeKey.ANNOTATION_URL_HIGHLIGHT.value: "bold " + palette.blue,
                ThemeKey.ANNOTATION_SEARCH_CONTENT.value: "italic " + palette.grey2,
                # PALETTE COLORS
                ThemeKey.RED.value: palette.red,
                ThemeKey.YELLOW.value: palette.yellow,
                ThemeKey.GREEN.value: palette.green,
                ThemeKey.CYAN.value: palette.cyan,
                ThemeKey.BLUE.value: palette.blue,
                ThemeKey.GREY_BLUE.value: palette.grey_blue,
                ThemeKey.GREY1.value: palette.grey1,
                ThemeKey.GREY2.value: palette.grey2,
                ThemeKey.GREY3.value: palette.grey3,
                ThemeKey.PURPLE.value: palette.purple,
                ThemeKey.ORANGE.value: palette.orange,
            }
        ),
        markdown_theme=Theme(
            styles={
                "markdown.code": palette.purple,
                "markdown.h1": "bold reverse",
                "markdown.h1.border": palette.grey3,
                "markdown.h2.border": palette.grey3,
                "markdown.h3": "bold " + palette.grey1,
                "markdown.h4": "bold " + palette.grey2,
                "markdown.item.bullet": palette.grey2,
                "markdown.item.number": palette.grey2,
            }
        ),
        code_theme=palette.code_theme,
        sub_agent_colors=[
            ThemeKey.YELLOW,
            ThemeKey.GREEN,
            ThemeKey.BLUE,
            ThemeKey.PURPLE,
        ],
    )


APP_THEME = Theme(
    styles={
        ThemeKey.LINES.value: "grey70",
        # DIFF
        ThemeKey.DIFF_REMOVE.value: "#333333 on #ffa8b4",
        ThemeKey.DIFF_ADD.value: "#333333 on #69db7c",
        # ERROR
        ThemeKey.ERROR.value: "red",
        ThemeKey.ERROR_BOLD.value: "bold red",
        ThemeKey.INTERRUPT.value: "reverse bold red",
        # USER_INPUT
        ThemeKey.USER_INPUT.value: "cyan",
        ThemeKey.USER_INPUT_DIM.value: "cyan dim",
        ThemeKey.USER_INPUT_AT_PATTERN.value: "reverse medium_purple3",
        ThemeKey.USER_INPUT_SLASH_COMMAND.value: "reverse bold cyan",
        # METADATA
        ThemeKey.METADATA.value: "steel_blue",
        ThemeKey.METADATA_DIM.value: "dim steel_blue",
        ThemeKey.METADATA_BOLD.value: "bold steel_blue",
        # SPINNER_STATUS
        ThemeKey.SPINNER_STATUS.value: "orange1",
        ThemeKey.SPINNER_STATUS_BOLD.value: "bold orange1",
        # REMINDER
        ThemeKey.REMINDER.value: "medium_purple3",
        ThemeKey.REMINDER_BOLD.value: "bold medium_purple3",
        ThemeKey.REMINDER_DIM.value: "dim medium_purple3",
        # TOOL
        ThemeKey.INVALID_TOOL_CALL_ARGS.value: "yellow",
        ThemeKey.TOOL_NAME.value: "bold",
        ThemeKey.TOOL_PARAM_FILE_PATH.value: "green",
        ThemeKey.TOOL_PARAM.value: "green",
        ThemeKey.TOOL_PARAM_BOLD.value: "bold green",
        ThemeKey.TOOL_RESULT.value: "grey50",
        ThemeKey.TOOL_MARK.value: "bold",
        # THINKING
        ThemeKey.THINKING.value: "italic dim",
        ThemeKey.THINKING_BOLD.value: "bold italic dim",
        # TODO_ITEM
        ThemeKey.TODO_PENDING_MARK.value: "bold dim",
        ThemeKey.TODO_COMPLETED_MARK.value: "bold dim",
        ThemeKey.TODO_IN_PROGRESS_MARK.value: "bold dodger_blue1",
        ThemeKey.TODO_NEW_COMPLETED_MARK.value: "bold green",
        ThemeKey.TODO_PENDING.value: "dim bold",
        ThemeKey.TODO_COMPLETED.value: "dim strike",
        ThemeKey.TODO_IN_PROGRESS.value: "dodger_blue1 bold",
        ThemeKey.TODO_NEW_COMPLETED.value: "green bold strike",
        # WELCOME
        ThemeKey.WELCOME_HIGHLIGHT.value: "bold",
        ThemeKey.WELCOME_INFO.value: "dim",
        # RESUME
        ThemeKey.RESUME_FLAG.value: "green bold reverse",
        ThemeKey.RESUME_INFO.value: "green",
        # URL
        ThemeKey.ANNOTATION_URL.value: "blue",
        ThemeKey.ANNOTATION_URL_HIGHLIGHT.value: "bold blue",
        ThemeKey.ANNOTATION_SEARCH_CONTENT.value: "bright_black italic",
    }
)
