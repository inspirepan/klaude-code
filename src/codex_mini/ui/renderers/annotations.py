from rich.console import RenderableType
from rich.style import Style
from rich.text import Text

from codex_mini.protocol import model
from codex_mini.ui.base.theme import ThemeKey
from codex_mini.ui.renderers.common import create_grid, truncate_display
from codex_mini.ui.rich_ext.markdown import NoInsetMarkdown


def render_annotations(annotations: list[model.Annotation]) -> RenderableType:
    grid = create_grid()
    for annotation in annotations:
        match annotation.type:
            case "url_citation":
                if not annotation.url_citation:
                    continue
                url = Text(annotation.url_citation.title, style=ThemeKey.ANNOTATION_URL)
                # Layer additional visual effects without needing Console
                url.stylize(Style(reverse=True, bold=True, underline=True, link=annotation.url_citation.url))
                grid.add_row(Text("○", style=ThemeKey.ANNOTATION_URL_HIGHLIGHT), url)
                grid.add_row(
                    "",
                    NoInsetMarkdown(
                        truncate_display(annotation.url_citation.content, max_lines=30),
                        style=ThemeKey.ANNOTATION_SEARCH_CONTENT,
                    ),
                )
                grid.add_row("", "")
            # case _:
            #     # Unknown annotation types are ignored for now
            #     continue
    return grid
