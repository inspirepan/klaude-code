import re
import sys

from .colors import ColorStyle
from .console import console


def clear_last_line():
    sys.stdout.write('\033[F\033[K')
    sys.stdout.flush()


def get_prompt_toolkit_color(color_style: ColorStyle) -> str:
    """Get hex color value for prompt-toolkit from theme"""
    style_value = console.console.get_style(color_style.value)
    if hasattr(style_value, 'color') and style_value.color:
        # Convert rich Color to hex
        if hasattr(style_value.color, 'triplet'):
            r, g, b = style_value.color.triplet
            return f'#{r:02x}{g:02x}{b:02x}'
        elif hasattr(style_value.color, 'number'):
            # Handle palette colors
            return f'ansi{style_value.color.number}'
    # Fallback to extract from rgb() string
    rgb_match = re.search(r'rgb\((\d+),(\d+),(\d+)\)', str(style_value))
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        return f'#{r:02x}{g:02x}{b:02x}'
    return '#ffffff'


def get_prompt_toolkit_style() -> dict:
    """Get prompt-toolkit style dict based on current theme"""
    return {
        'completion-menu': 'bg:default',
        'completion-menu.border': 'bg:default',
        'scrollbar.background': 'bg:default',
        'scrollbar.button': 'bg:default',
        'completion-menu.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.meta.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.completion.current': f'noreverse bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)}',
        'completion-menu.meta.completion.current': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)}',
    }


def get_inquirer_style() -> dict:
    """Get InquirerPy style dict based on current theme"""
    return {
        'question': f'bold {get_prompt_toolkit_color(ColorStyle.HIGHLIGHT)}',
        'pointer': f'fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)} bg:default',
    }
