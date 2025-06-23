from simple_term_menu import TerminalMenu


def ask_user(options: list[str]) -> int:
    menu = TerminalMenu(
        options,
        clear_menu_on_exit=True,
    )
    idx = menu.show()
    return idx
