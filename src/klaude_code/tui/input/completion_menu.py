from __future__ import annotations

import prompt_toolkit.layout.menus as pt_menus
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import Completion
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples, fragment_list_width, to_formatted_text
from prompt_toolkit.layout.containers import Container, FloatContainer, Window
from prompt_toolkit.layout.controls import UIContent
from prompt_toolkit.layout.menus import CompletionsMenu, MultiColumnCompletionsMenu
from prompt_toolkit.layout.utils import explode_text_fragments
from prompt_toolkit.utils import get_cwidth

COMPLETION_TRUNCATION_SYMBOL = "…"


def customize_completion_menus(container: Container) -> None:
    """Apply Klaude-specific completion menu positioning and rendering."""

    _left_align_completion_menus(container)
    _patch_completion_menu_controls(container)


def _trim_formatted_text_with_ellipsis(
    formatted_text: StyleAndTextTuples,
    max_width: int,
) -> tuple[StyleAndTextTuples, int]:
    """Trim completion text and use a single unicode ellipsis on overflow."""

    width = fragment_list_width(formatted_text)
    if width <= max_width:
        return formatted_text, width

    if max_width <= 0:
        return [], 0

    ellipsis_width = get_cwidth(COMPLETION_TRUNCATION_SYMBOL)
    remaining_width = max(0, max_width - ellipsis_width)
    result: StyleAndTextTuples = []

    for style_and_ch in explode_text_fragments(formatted_text):
        ch_width = get_cwidth(style_and_ch[1])
        if ch_width <= remaining_width:
            result.append(style_and_ch)
            remaining_width -= ch_width
            continue
        break

    result.append(("", COMPLETION_TRUNCATION_SYMBOL))
    used_width = max_width - remaining_width
    return result, used_width


def _left_align_completion_menus(container: Container) -> None:
    """Force completion menus to render at column 0."""

    if isinstance(container, FloatContainer):
        for flt in container.floats:
            if isinstance(flt.content, (CompletionsMenu, MultiColumnCompletionsMenu)):
                flt.xcursor = False
                flt.left = 0

    for child in container.get_children():
        _left_align_completion_menus(child)


def _patch_completion_menu_controls(container: Container) -> None:
    """Replace prompt_toolkit completion menu controls with customized versions."""

    if isinstance(container, Window):
        content = container.content
        if isinstance(content, pt_menus.CompletionsMenuControl) and not isinstance(
            content, _KlaudeCompletionsMenuControl
        ):
            container.content = _KlaudeCompletionsMenuControl()

    for child in container.get_children():
        _patch_completion_menu_controls(child)


_DIM_FRAGMENT_CLASSES = (
    "class:meta",
    "class:skill.project",
    "class:skill.user",
    "class:skill.system",
)


def _strip_dim_fg(fragments: StyleAndTextTuples) -> StyleAndTextTuples:
    """Strip dim/accent class tokens so the selection foreground takes effect."""

    result: StyleAndTextTuples = []
    for item in fragments:
        style = item[0]
        for cls in _DIM_FRAGMENT_CLASSES:
            if cls in style:
                style = style.replace(cls, "")
        style = " ".join(style.split())
        if len(item) >= 3:
            result.append((style, item[1], item[2]))  # ty: ignore[index-out-of-bounds]
        else:
            result.append((style, item[1]))
    return result


class _KlaudeCompletionsMenuControl(pt_menus.CompletionsMenuControl):
    """CompletionsMenuControl with stable 2-char left prefix."""

    _PREFIX_WIDTH = 2

    def _get_menu_width(self, max_width: int, complete_state: pt_menus.CompletionState) -> int:  # pyright: ignore[reportPrivateImportUsage]
        """Return the width of the main column."""

        return min(
            max_width,
            max(
                self.MIN_WIDTH,
                max(get_cwidth(c.display_text) for c in complete_state.completions) + 3,
            ),
        )

    def create_content(self, width: int, height: int) -> UIContent:
        complete_state = get_app().current_buffer.complete_state
        if complete_state:
            completions = complete_state.completions
            index = complete_state.complete_index

            menu_width = self._get_menu_width(width, complete_state)
            menu_meta_width = self._get_menu_meta_width(width - menu_width, complete_state)
            show_meta = self._show_meta(complete_state)

            def get_line(i: int) -> StyleAndTextTuples:
                completion = completions[i]
                is_current_completion = i == index

                result = self._get_menu_item_fragments_with_cursor(
                    completion,
                    is_current_completion,
                    menu_width,
                    space_after=True,
                )
                if show_meta:
                    result += self._get_menu_item_meta_fragments(
                        completion,
                        is_current_completion,
                        menu_meta_width,
                    )
                return result

            return UIContent(
                get_line=get_line,
                cursor_position=Point(x=0, y=index or 0),
                line_count=len(completions),
            )

        return UIContent()

    def _get_menu_item_fragments_with_cursor(
        self,
        completion: Completion,
        is_current_completion: bool,
        width: int,
        *,
        space_after: bool = False,
    ) -> StyleAndTextTuples:
        if is_current_completion:
            style_str = f"class:completion-menu.completion.current {completion.style} {completion.selected_style}"
            prefix = "→ "
        else:
            style_str = "class:completion-menu.completion " + completion.style
            prefix = "  "

        max_text_width = width - self._PREFIX_WIDTH - (1 if space_after else 0)
        text, text_width = _trim_formatted_text_with_ellipsis(completion.display, max_text_width)
        padding = " " * (width - self._PREFIX_WIDTH - text_width)

        if is_current_completion:
            text = _strip_dim_fg(text)

        return to_formatted_text(
            [("", prefix), *text, ("", padding)],
            style=style_str,
        )

    def _get_menu_item_meta_fragments(
        self,
        completion: Completion,
        is_current_completion: bool,
        width: int,
    ) -> StyleAndTextTuples:
        if is_current_completion:
            style_str = "class:completion-menu.meta.completion.current"
        else:
            style_str = "class:completion-menu.meta.completion"

        text, text_width = _trim_formatted_text_with_ellipsis(completion.display_meta, width - 2)
        padding = " " * (width - 1 - text_width)
        return to_formatted_text(
            [("", " "), *text, ("", padding)],
            style=style_str,
        )
