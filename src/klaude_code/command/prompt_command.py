from importlib.resources import files

import yaml

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, model, op
from klaude_code.trace import log_debug


class PromptCommand(CommandABC):
    """Command that loads a prompt from a markdown file."""

    def __init__(self, filename: str, command_name: str | None = None):
        self._filename = filename
        self._command_name = command_name or filename.replace("prompt_", "").replace("prompt-", "").replace(".md", "")
        self._content: str | None = None
        self._metadata: dict[str, str] = {}

    @property
    def name(self) -> str | commands.CommandName:
        return self._command_name

    @property
    def template_name(self) -> str:
        """filename of the markdown prompt template in the command package."""
        return self._filename

    def _ensure_loaded(self):
        if self._content is not None:
            return

        try:
            raw_text = files("klaude_code.command").joinpath(self.template_name).read_text(encoding="utf-8")

            if raw_text.startswith("---"):
                parts = raw_text.split("---", 2)
                if len(parts) >= 3:
                    self._metadata = yaml.safe_load(parts[1]) or {}
                    self._content = parts[2].strip()
                    return

            self._metadata = {}
            self._content = raw_text
        except (OSError, yaml.YAMLError) as e:
            log_debug(f"Failed to load prompt template {self.template_name}: {e}")
            self._metadata = {"description": "Error loading template"}
            self._content = f"Error loading template: {self.template_name}"

    @property
    def summary(self) -> str:
        self._ensure_loaded()
        return self._metadata.get("description", f"Execute {self.name} command")

    @property
    def support_addition_params(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        self._ensure_loaded()
        template_content = self._content or ""
        user_input_text = user_input.text.strip() or "<none>"

        if "$ARGUMENTS" in template_content:
            final_prompt = template_content.replace("$ARGUMENTS", user_input_text)
        else:
            final_prompt = template_content
            if user_input_text:
                final_prompt += f"\n\nAdditional Instructions:\n{user_input_text}"

        return CommandResult(
            operations=[
                op.RunAgentOperation(
                    session_id=agent.session.id,
                    input=model.UserInputPayload(text=final_prompt, images=user_input.images),
                )
            ]
        )
