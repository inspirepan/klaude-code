from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.core import Agent
from codex_mini.core.prompt import get_init_prompt
from codex_mini.protocol.commands import CommandName


class InitCommand(CommandABC):
    """Initialize a new CLAUDE.md file with codebase documentation"""

    @property
    def name(self) -> CommandName:
        return CommandName.INIT

    @property
    def summary(self) -> str:
        # return "initialize a new CLAUDE.md file with codebase documentation"
        return "create an AGENTS.md file with instructions for Codex"

    @property
    def support_addition_params(self) -> bool:
        return True

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        input = get_init_prompt()
        if len(raw.strip()) > 0:
            input += f"""\n
Additional Instructions:
{raw.strip()}\n"""

        return CommandResult(agent_input=input)
