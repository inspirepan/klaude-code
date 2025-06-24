from ..user_input import Command


class CostCommand(Command):
    def get_name(self) -> str:
        return 'cost'

    def get_command_desc(self) -> str:
        return 'Show the total cost and duration of the current session'
