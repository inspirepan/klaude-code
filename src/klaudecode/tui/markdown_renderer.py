from typing import Optional, Union

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.markdown import CodeBlock, Heading, HorizontalRule, Markdown, TableElement
from rich.rule import Rule
from rich.style import Style
from rich.table import Table

from .colors import ColorStyle


class CustomCodeBlock(CodeBlock):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()

        # Select color scheme based on theme
        from .console import console as global_console

        if global_console.is_dark_theme():
            theme = 'lightbulb'
        else:
            theme = 'lovelace'

        from rich.syntax import Syntax

        # Create Syntax without background
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=theme,
            word_wrap=True,
            padding=1,
            background_color='default',
        )
        yield syntax


class CustomTableElement(TableElement):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
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
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield Rule(style=ColorStyle.LINE, characters='╌')


class CustomHeading(Heading):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = 'left'

        if self.tag == 'h1':
            text.stylize(ColorStyle.HEADER_2.bold + Style(underline=True))
            yield text
        elif self.tag == 'h2':
            text.stylize(ColorStyle.HEADER_2.bold + Style(underline=False))
            yield text
            yield Rule(style=ColorStyle.LINE, characters='╌')
        elif self.tag == 'h3':
            text.stylize(ColorStyle.HEADER_3.bold)
            yield text
        else:
            text.stylize(ColorStyle.HIGHLIGHT.style + Style(bold=False, italic=False, underline=False))
            yield text


class CustomMarkdown(Markdown):
    elements = Markdown.elements.copy()
    elements['heading_open'] = CustomHeading
    elements['hr'] = CustomHorizontalRule
    elements['table_open'] = CustomTableElement
    elements['fence'] = CustomCodeBlock
    elements['code_block'] = CustomCodeBlock

    def __init__(self, *args, **kwargs):
        # Disable hyperlink rendering to preserve original format
        kwargs['hyperlinks'] = False
        super().__init__(*args, **kwargs)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Create temporary theme to override styles
        from rich.theme import Theme

        temp_theme = Theme(
            {
                'markdown.code': ColorStyle.INLINE_CODE.style,
                'markdown.item.bullet': ColorStyle.HINT.style,
                'markdown.item.number': ColorStyle.HINT.style,
                'markdown.block_quote': ColorStyle.INFO.style,
            }
        )

        # Use push_theme and pop_theme to temporarily override styles
        console.push_theme(temp_theme)

        try:
            # Call parent class render method
            yield from super().__rich_console__(console, options)
        finally:
            # Restore original theme
            console.pop_theme()


def render_markdown(text: str, style: Optional[Union[str, Style]] = None) -> Group:
    """Convert Markdown syntax to Rich Group using CustomMarkdown"""
    if not text:
        return Group()

    custom_md = CustomMarkdown(text, style=style or 'none')
    return Group(custom_md)
