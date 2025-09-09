from typing import Any

from codex_mini.command.command_abc import CommandABC
from codex_mini.config import load_config
from codex_mini.protocol.events import DeveloperMessageEvent, Event
from codex_mini.protocol.model import DeveloperMessageItem


class ModelCommand(CommandABC):
    """Display or change the model configuration."""

    @property
    def name(self) -> str:
        return "model"

    @property
    def summary(self) -> str:
        return "Set the AI model"

    async def run(self, raw: str, session_id: str | None) -> tuple[dict[str, Any] | None, list[Event]]:
        # Parse arguments: /model [model_name]
        parts = raw.strip().split()
        args = parts[1:] if len(parts) > 1 else []

        config = load_config()

        if not args:
            # No arguments: show current model and available models
            current_model = config.main_model or "not set"
            lines = [f"Current model: {current_model}", "", "Available models:"]

            if not config.model_list:
                lines.append("  No available models, please check config file")
            else:
                for model in config.model_list:
                    star = " ★" if model.model_name == config.main_model else ""
                    lines.append(f"  {model.model_name}{star}")
                lines.append("")
                lines.append("Use /model <model_name> to switch model")

            message = "\n".join(lines)
        else:
            # Has argument: try to set model
            target_model = args[0]
            available_models = [m.model_name for m in config.model_list]

            if target_model not in available_models:
                message = f"Model '{target_model}' not found. Available models: {', '.join(available_models)}"
            else:
                # Update config
                config.main_model = target_model
                try:
                    await config.save()
                    message = f"Set main model to: {target_model}\n\nNote: need to restart session to take effect."
                except Exception as e:
                    message = f"Failed to save config: {e}"

        event = DeveloperMessageEvent(session_id=session_id or "default", item=DeveloperMessageItem(content=message))

        return None, [event]
