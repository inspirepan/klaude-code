import sys

from .colors import ColorStyle
from .console import console


def clear_last_line():
    sys.stdout.write('\033[F\033[K')
    sys.stdout.flush()


def get_prompt_toolkit_color(color_style: ColorStyle) -> str:
    """Get hex color value for prompt-toolkit from theme"""
    style_value = console.console.get_style(color_style.value)

    # Check if it's a direct ANSI color name
    style_str = str(style_value)
    basic_colors = ['white', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'black']
    if style_str in basic_colors:
        return f'ansi{style_str}'
    elif style_str == 'bright_white':
        return 'ansiwhite'
    elif style_str.startswith('bright_') and style_str[7:] in basic_colors:
        color_name = style_str.replace('_', '')
        return f'ansi{color_name}'

    return style_str


def get_prompt_toolkit_style() -> dict:
    """Get prompt-toolkit style dict based on current theme"""
    return {
        'completion-menu': 'bg:default',
        'completion-menu.border': 'bg:default',
        'scrollbar.background': 'bg:default',
        'scrollbar.button': 'bg:default',
        'completion-menu.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.meta.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.completion.current': f'noreverse bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)} bold',
        'completion-menu.meta.completion.current': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)} bold',
    }


def get_inquirer_style() -> dict:
    """Get InquirerPy style dict based on current theme"""
    return {
        'question': f'bold {get_prompt_toolkit_color(ColorStyle.HIGHLIGHT)}',
        'pointer': f'bold fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED)} bg:default',
    }
