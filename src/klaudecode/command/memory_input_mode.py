from ..user_input import InputModeCommand


class MemoryMode(InputModeCommand):
    def get_name(self) -> str:
        return 'memory'

    def _get_prompt(self) -> str:
        return '#'

    def _get_color(self) -> str:
        return '#b3b9f4'

    def get_placeholder(self) -> str:
        return 'type to memorize...'

    def binding_key(self) -> str:
        return '#'
