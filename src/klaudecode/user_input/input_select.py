import asyncio
from typing import Optional

from InquirerPy import get_style, inquirer

from ..tui import clear_last_line, get_inquirer_style


async def user_select(options: list[str], title: str = None) -> Optional[int]:
    if not options:
        return None

    indexed_choices = [{'name': choice, 'value': idx} for idx, choice in enumerate(options)]
    style = get_style(get_inquirer_style(), style_override=True)
    try:
        idx = await inquirer.select(message=title, choices=indexed_choices, style=style).execute_async()
    except (KeyboardInterrupt, asyncio.CancelledError):
        return None
    clear_last_line()
    return idx
