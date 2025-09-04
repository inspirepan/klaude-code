from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from codex_mini.protocol import LLMConfigParameter, Reasoning, Thinking
from codex_mini.trace import log

config_path = Path.home() / ".config" / "codex-mini" / "config.json"


class LLMConfig(BaseModel):
    model_name: str
    protocol: Literal["chat_completion", "responses", "anthropic"] = "responses"
    llm_parameter: LLMConfigParameter


class Config(BaseModel):
    model_list: list[LLMConfig]
    main_model: str

    def get_main_model_config(self) -> LLMConfig:
        main_model = next(
            (model for model in self.model_list if model.model_name == self.main_model),
            None,
        )
        if main_model is None:
            raise ValueError(f"Main model {self.main_model} not found")
        return main_model


def get_example_config() -> Config:
    return Config(
        main_model="gpt-5",
        model_list=[
            LLMConfig(
                model_name="gpt-5",
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
        ],
    )


def load_config() -> Config:
    if not config_path.exists():
        log(f"Config file not found: {config_path}")
        example_config = get_example_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _ = config_path.write_text(example_config.model_dump_json(indent=2))
        log(f"Example config created at: {config_path}")
        log("[bold]Please edit the config file to set up your models[/bold]")
        return example_config

    config_json = config_path.read_text()
    config = Config.model_validate_json(config_json)
    return config
