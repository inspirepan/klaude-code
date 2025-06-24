from .user_input import InputModeCommand, register_input_mode

# Input Modes
# ---------------------


class PlanMode(InputModeCommand):
    def get_name(self) -> str:
        return 'plan'

    def _get_prompt(self) -> str:
        return '*'

    def _get_color(self) -> str:
        return '#6aa4a5'

    def get_placeholder(self) -> str:
        return 'type to start planning...'

    def get_next_mode_name(self) -> str:
        return 'plan'

    def binding_key(self) -> str:
        return '*'

    # TODO: Implement handle


class BashMode(InputModeCommand):
    def get_name(self) -> str:
        return 'bash'

    def _get_prompt(self) -> str:
        return '!'

    def _get_color(self) -> str:
        return '#ea3386'

    def get_placeholder(self) -> str:
        return 'type a bash command...'

    def binding_key(self) -> str:
        return '!'

    # TODO: Implement handle


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

    # TODO: Implement handle


register_input_mode(PlanMode())
register_input_mode(BashMode())
register_input_mode(MemoryMode())
