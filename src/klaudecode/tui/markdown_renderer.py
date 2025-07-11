from typing import Optional, Union

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.markdown import CodeBlock, Heading, HorizontalRule, Markdown, TableElement
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .colors import ColorStyle


class CustomCodeBlock(CodeBlock):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()

        # Select color scheme based on theme
        from .console import console as global_console

        if global_console.is_dark_theme():
            theme = 'github-dark'
        else:
            theme = 'sas'

        from rich.syntax import Syntax

        # Create Syntax without background
        syntax = Syntax(
            code,
            self.lexer_name,
            theme=theme,
            word_wrap=True,
            padding=0,
            background_color='default',
        )
        yield Panel.fit(syntax, title=Text(self.lexer_name, style=ColorStyle.INLINE_CODE), border_style=ColorStyle.LINE, title_align='left')


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
        yield Group(
            '',
            Rule(style=ColorStyle.LINE, characters='═'),
            '',
        )


class CustomHeading(Heading):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text
        text.justify = 'left'
        if self.tag == 'h1':
            text.stylize(Style(underline=True, bold=True))
        elif self.tag == 'h2':
            text.stylize(Style(bold=True))
            rule = Rule(style=ColorStyle.LINE, characters='╌')
            # Check if we need to add empty line before H2
            markdown_instance = getattr(console, '_current_markdown', None)
            if markdown_instance and getattr(markdown_instance, '_has_content', False):
                text = Group('', text, rule)
            else:
                text = Group(text, rule)

        elif self.tag == 'h3':
            text.stylize(Style(bold=True))

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
        self._has_content = False

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        # Create temporary theme to override styles
        from rich.theme import Theme

        temp_theme = Theme(
            {
                'markdown.code': ColorStyle.INLINE_CODE.style,
                'markdown.item.bullet': ColorStyle.HINT.style,
                'markdown.item.number': ColorStyle.HINT.style,
                'markdown.block_quote': ColorStyle.INFO.style,
                'markdown.h1': ColorStyle.HEADER_1.style,
                'markdown.h2': ColorStyle.HEADER_2.style,
                'markdown.h3': ColorStyle.HEADER_3.style,
                'markdown.h4': ColorStyle.HEADER_4.style,
            }
        )

        # Use push_theme and pop_theme to temporarily override styles
        console.push_theme(temp_theme)

        # Set current markdown instance to console for CustomHeading to use
        console._current_markdown = self

        try:
            # Call parent class render method
            first_element = True
            for element in super().__rich_console__(console, options):
                if first_element:
                    first_element = False
                else:
                    self._has_content = True
                yield element
        finally:
            # Restore original theme
            console.pop_theme()
            # Clean up temporary attributes
            if hasattr(console, '_current_markdown'):
                delattr(console, '_current_markdown')


def render_markdown(text: str, style: Optional[Union[str, Style]] = None) -> Group:
    """Convert Markdown syntax to Rich Group using CustomMarkdown"""
    if not text:
        return Group()

    custom_md = CustomMarkdown(text, style=style or 'none')
    return Group(custom_md)
