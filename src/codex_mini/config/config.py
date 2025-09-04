from pathlib import Path

import yaml
from pydantic import BaseModel

from codex_mini.protocol import (
    LLMClientProtocol,
    LLMConfigParameter,
    Reasoning,
    Thinking,
)
from codex_mini.protocol.llm_parameter import (
    LLMConfigModelParameter,
    LLMConfigProviderParameter,
)
from codex_mini.trace import log

config_path = Path.home() / ".config" / "codex-mini" / "config.yaml"


class ProviderConfig(BaseModel):
    provider: LLMConfigProviderParameter
    models: dict[str, LLMConfigModelParameter]


class Config(BaseModel):
    providers: dict[str, ProviderConfig]
    main_model: str

    def get_main_model_config(self) -> LLMConfigParameter:
        provider_name, model_name = self.main_model.split("/", 1)
        if provider_name not in self.providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        if model_name not in self.providers[provider_name].models:
            raise ValueError(f"Unknown model: {model_name}")
        return LLMConfigParameter(
            **self.providers[provider_name].provider.model_dump(),
            **self.providers[provider_name].models[model_name].model_dump(),
        )


def get_example_config() -> Config:
    return Config(
        main_model="openai/gpt-5",
        providers={
            "openai": ProviderConfig(
                provider=LLMConfigProviderParameter(
                    protocol=LLMClientProtocol.RESPONSES,
                    api_key="sk-1234567890",
                    base_url="https://api.openai.com/v1",
                    is_azure=False,
                    azure_api_version="2023-03-15-preview",
                ),
                models={
                    "gpt-5": LLMConfigModelParameter(
                        model="gpt-5-2025-08-07",
                        temperature=1.0,
                        max_tokens=8192,
                        verbosity="medium",
                        reasoning=Reasoning(effort="high", summary="auto"),
                    )
                },
            ),
            "openrouter": ProviderConfig(
                provider=LLMConfigProviderParameter(
                    protocol=LLMClientProtocol.OPENAI,
                    api_key="sk-1234567890",
                    base_url="https://api.openrouter.com/v1",
                    is_azure=False,
                    azure_api_version="2023-03-15-preview",
                ),
                models={
                    "sonnet-4": LLMConfigModelParameter(
                        model="anthropic/claude-sonnet-4",
                        temperature=1.0,
                        max_tokens=8192,
                        thinking=Thinking(type="enabled", budget_tokens=1024),
                    )
                },
            ),
        },
    )


def load_config() -> Config:
    if not config_path.exists():
        log(f"Config file not found: {config_path}")
        example_config = get_example_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_dict = example_config.model_dump(mode="json", exclude_none=True)
        _ = config_path.write_text(
            yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
        )
        log(f"Example config created at: {config_path}")
        log("[bold]Please edit the config file to set up your models[/bold]")
        return example_config

    config_yaml = config_path.read_text()
    config_dict = yaml.safe_load(config_yaml)
    config = Config.model_validate(config_dict)
    return config
