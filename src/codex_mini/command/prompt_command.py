from importlib.resources import files

import yaml

from codex_mini.command.command_abc import CommandABC, CommandResult
from codex_mini.core import Agent
from codex_mini.protocol.commands import CommandName


class PromptCommand(CommandABC):
    """Command that loads a prompt from a markdown file."""

    def __init__(self, filename: str, command_name: str | None = None):
        self._filename = filename
        self._command_name = command_name or filename.replace("prompt_", "").replace("prompt-", "").replace(".md", "")
        self._content: str | None = None
        self._metadata: dict[str, str] = {}

    @property
    def name(self) -> str | CommandName:
        return self._command_name

    @property
    def template_name(self) -> str:
        """filename of the markdown prompt template in the command package."""
        return self._filename

    def _ensure_loaded(self):
        if self._content is not None:
            return

        try:
            raw_text = files("codex_mini.command").joinpath(self.template_name).read_text(encoding="utf-8")

            if raw_text.startswith("---"):
                parts = raw_text.split("---", 2)
                if len(parts) >= 3:
                    self._metadata = yaml.safe_load(parts[1]) or {}
                    self._content = parts[2].strip()
                    return

            self._metadata = {}
            self._content = raw_text
        except Exception:
            self._metadata = {"description": "Error loading template"}
            self._content = f"Error loading template: {self.template_name}"

    @property
    def summary(self) -> str:
        self._ensure_loaded()
        return self._metadata.get("description", f"Execute {self.name} command")

    @property
    def support_addition_params(self) -> bool:
        return True

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        self._ensure_loaded()
        template_content = self._content or ""
        user_input = raw.strip()

        if "$ARGUMENTS" in template_content:
            final_prompt = template_content.replace("$ARGUMENTS", user_input)
        else:
            final_prompt = template_content
            if user_input:
                final_prompt += f"\n\nAdditional Instructions:\n{user_input}"

        return CommandResult(agent_input=final_prompt)
