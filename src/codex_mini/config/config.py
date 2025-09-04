from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from codex_mini.protocol import LLMConfigParameter, Reasoning, Thinking
from codex_mini.trace import log

config_path = Path.home() / ".config" / "codex-mini" / "config.json"


class LLMConfig(BaseModel):
    protocol: Literal["chat_completion", "responses", "anthropic"] = "responses"

    llm_parameter: LLMConfigParameter


class Config(BaseModel):
    llm_config: LLMConfig


def get_example_config() -> Config:
    return Config(
        llm_config=LLMConfig(
            protocol="responses",
            llm_parameter=LLMConfigParameter(
                model="gpt-5-2025-08-07",
                base_url="https://api.openai.com/v1",
                api_key="sk-1234567890",
                is_azure=False,
                azure_api_version="2023-03-15-preview",
                temperature=1.0,
                max_tokens=8192,
                verbosity="medium",
                reasoning=Reasoning(effort="high", summary="auto"),
                thinking=Thinking(type="enabled", budget_tokens=1024),
            ),
        )
    )


def load_config() -> Config:
    if not config_path.exists():
        log(f"Config file not found: {config_path}")
        example_config = get_example_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _ = config_path.write_text(example_config.model_dump_json(indent=2))
        log(f"Example config created at: {config_path}")
        return example_config

    config_json = config_path.read_text()
    config = Config.model_validate_json(config_json)
    return config
