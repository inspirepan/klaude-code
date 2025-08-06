from typing import Optional, Union

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.markdown import CodeBlock, Heading, HorizontalRule, Markdown, TableElement
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table

from .colors import ColorStyle


class CustomCodeBlock(CodeBlock):
    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        code = str(self.text).rstrip()

        # Select color scheme based on theme
        from .console import console as global_console

        if global_console.is_dark_theme():
            theme = "github-dark"
        else:
            theme = "sas"

        from rich.syntax import Syntax

        # Create Syntax without background
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=theme,
            word_wrap=True,
            padding=0,
            background_color="default",
        )
        yield Panel.fit(
            syntax,
            # title=Text(self.lexer_name, style=ColorStyle.INLINE_CODE),
            border_style=ColorStyle.LINE,
            box=box.HORIZONTALS,
            title_align="left",
        )


class CustomTableElement(TableElement):
    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        table = Table(box=box.SQUARE, border_style=ColorStyle.LINE.style)

        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                table.add_column(column.content)

        if self.body is not None:
            for row in self.body.rows:
                row_content = [element.content for element in row.cells]
                table.add_row(*row_content)

        yield table


class CustomHorizontalRule(HorizontalRule):
    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        yield Group(
            "",
            Rule(style=ColorStyle.LINE, characters="═"),
            "",
        )


class CustomHeading(Heading):
    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        text = self.text
        text.justify = "left"
        if self.tag == "h1":
            text.stylize(Style(underline=True, bold=True))
        elif self.tag == "h2":
            text.stylize(Style(bold=True))
            # Only add rule if heading has content
            if str(text).strip():
                rule = Rule(style=ColorStyle.LINE, characters="╌")
                text = Group(text, rule)

        elif self.tag == "h3":
            text.stylize(Style(bold=True))

        yield text


class CustomMarkdown(Markdown):
    elements = Markdown.elements.copy()
    elements["heading_open"] = CustomHeading
    elements["hr"] = CustomHorizontalRule
    elements["table_open"] = CustomTableElement
    elements["fence"] = CustomCodeBlock
    elements["code_block"] = CustomCodeBlock

    def __init__(self, *args, **kwargs):
        # Disable hyperlink rendering to preserve original format
        kwargs["hyperlinks"] = False
        super().__init__(*args, **kwargs)

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        # Call parent class render method
        for element in super().__rich_console__(console, options):
            yield element


def render_markdown(text: str, style: Optional[Union[str, Style]] = None) -> Group:
    """Convert Markdown syntax to Rich Group using CustomMarkdown"""
    if not text:
        return Group()

    custom_md = CustomMarkdown(text, style=style or "none")
    return Group(custom_md)
