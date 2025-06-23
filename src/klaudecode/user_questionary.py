from InquirerPy import get_style, inquirer

from .tui import clear_last_line


async def user_menu_query(options: list[str], title: str = None) -> int:
    if not options:
        return None

    indexed_choices = [{'name': choice, 'value': idx} for idx, choice in enumerate(options)]
    style = get_style({'question': 'bold ansiwhite'}, style_override=False)
    idx = await inquirer.select(message=title, choices=indexed_choices, style=style).execute_async()
    clear_last_line()
    return idx
