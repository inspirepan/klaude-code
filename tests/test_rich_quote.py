from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from klaude_code.tui.components.rich.quote import Quote, TreeQuote


def test_quote_does_not_pad_to_full_width() -> None:
    console = Console(width=40, record=True)
    console.print(Quote(Text("hello world")))

    out = console.export_text()
    assert out.splitlines()[0] == "▌ hello world"


def test_quote_measure_reflects_content_width() -> None:
    console = Console(width=80)
    renderable = Quote(Text("hello world"))

    measurement = console.measure(renderable, options=console.options)
    assert measurement.maximum == cell_len("▌ hello world")
    assert measurement.maximum < console.width


def test_treequote_measure_reflects_content_width() -> None:
    console = Console(width=80)
    renderable = TreeQuote(Text("hello"), prefix_first="* ")

    measurement = console.measure(renderable, options=console.options)
    assert measurement.maximum == cell_len("* hello")
    assert measurement.maximum < console.width
