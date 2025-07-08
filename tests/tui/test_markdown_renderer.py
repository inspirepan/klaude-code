import pytest
from rich.style import Style
from rich.text import Text

from klaudecode.tui.markdown_renderer import _process_inline_formatting, render_markdown


class TestInlineFormatting:
    def test_bold_with_asterisks(self):
        result = _process_inline_formatting('**bold text**')
        assert len(result.spans) == 1
        assert result.spans[0].style.bold is True
        assert 'bold text' in str(result)

    def test_bold_with_underscores(self):
        result = _process_inline_formatting('__bold text__')
        assert len(result.spans) == 1
        assert result.spans[0].style.bold is True
        assert 'bold text' in str(result)

    def test_italic_with_asterisks(self):
        result = _process_inline_formatting('*italic text*')
        assert len(result.spans) == 1
        assert result.spans[0].style.italic is True
        assert 'italic text' in str(result)

    def test_italic_with_underscores(self):
        result = _process_inline_formatting('_italic text_')
        assert len(result.spans) == 1
        assert result.spans[0].style.italic is True
        assert 'italic text' in str(result)

    def test_bold_italic_with_triple_asterisks(self):
        result = _process_inline_formatting('***bold italic text***')
        assert len(result.spans) == 1
        assert result.spans[0].style.bold is True
        assert result.spans[0].style.italic is True
        assert 'bold italic text' in str(result)

    def test_mixed_formatting(self):
        result = _process_inline_formatting('This has **bold** and *italic* text')
        bold_span = None
        italic_span = None
        for span in result.spans:
            if span.style.bold and not span.style.italic:
                bold_span = span
            elif span.style.italic and not span.style.bold:
                italic_span = span
        
        assert bold_span is not None
        assert italic_span is not None

    def test_code_formatting(self):
        result = _process_inline_formatting('This has `code` text')
        assert len(result.spans) >= 1
        code_span = result.spans[0]
        assert 'code' in str(result)

    def test_strikethrough_formatting(self):
        result = _process_inline_formatting('~~strikethrough text~~')
        assert len(result.spans) == 1
        assert result.spans[0].style.strike is True
        assert 'strikethrough text' in str(result)

    def test_no_formatting(self):
        result = _process_inline_formatting('plain text')
        assert len(result.spans) == 0
        assert str(result) == 'plain text'

    def test_nested_asterisks_priority(self):
        result = _process_inline_formatting('***text*** **text** *text*')
        bold_italic_count = 0
        bold_only_count = 0
        italic_only_count = 0
        
        for span in result.spans:
            if span.style.bold and span.style.italic:
                bold_italic_count += 1
            elif span.style.bold and not span.style.italic:
                bold_only_count += 1
            elif span.style.italic and not span.style.bold:
                italic_only_count += 1
        
        assert bold_italic_count == 1
        assert bold_only_count == 1
        assert italic_only_count == 1


class TestMarkdownRenderer:
    def test_header_rendering(self):
        result = render_markdown('## Header Text')
        assert result is not None

    def test_list_rendering(self):
        result = render_markdown('- List item 1\n- List item 2')
        assert result is not None

    def test_quote_rendering(self):
        result = render_markdown('> This is a quote')
        assert result is not None

    def test_table_rendering(self):
        table_text = '''| Header 1 | Header 2 |
|----------|----------|
| Cell 1   | Cell 2   |'''
        result = render_markdown(table_text)
        assert result is not None

    def test_mixed_content(self):
        content = '''## Header
This is **bold** and *italic* text.
- List item with ***bold italic***
> Quote with `code`'''
        result = render_markdown(content)
        assert result is not None