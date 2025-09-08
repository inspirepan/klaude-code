import asyncio
from pathlib import Path

import yaml
from pydantic import BaseModel

from codex_mini.protocol.llm_parameter import (
    LLMClientProtocol,
    LLMConfigModelParameter,
    LLMConfigParameter,
    LLMConfigProviderParameter,
    OpenRouterPlugin,
    OpenRouterProviderRouting,
    Reasoning,
    Thinking,
)
from codex_mini.trace import log

config_path = Path.home() / ".config" / "codex-mini" / "config.yaml"


class ModelConfig(BaseModel):
    model_name: str
    provider: str
    model_params: LLMConfigModelParameter


class Config(BaseModel):
    provider_list: list[LLMConfigProviderParameter]
    model_list: list[ModelConfig]
    main_model: str
    theme: str | None = None

    def get_main_model_config(self) -> LLMConfigParameter:
        return self.get_model_config(self.main_model)

    def get_model_config(self, model_name: str) -> LLMConfigParameter:
        model = next(
            (model for model in self.model_list if model.model_name == model_name),
            None,
        )
        if model is None:
            raise ValueError(f"Unknown model: {model_name}")

        provider = next(
            (provider for provider in self.provider_list if provider.provider_name == model.provider),
            None,
        )
        if provider is None:
            raise ValueError(f"Unknown provider: {model.provider}")

        return LLMConfigParameter(
            **provider.model_dump(),
            **model.model_params.model_dump(),
        )

    async def save(self) -> None:
        """
        Save config to file.
        Notice: it won't preserve comments in the config file.
        """
        config_dict = self.model_dump(mode="json", exclude_none=True)

        def _save_config() -> None:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            _ = config_path.write_text(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))

        await asyncio.to_thread(_save_config)


def get_example_config() -> Config:
    return Config(
        main_model="gpt-5",
        provider_list=[
            LLMConfigProviderParameter(
                provider_name="openai",
                protocol=LLMClientProtocol.RESPONSES,
                api_key="sk-1234567890",
                base_url="https://api.openai.com/v1",
                is_azure=False,
                azure_api_version="2023-03-15-preview",
            ),
            LLMConfigProviderParameter(
                provider_name="openrouter",
                protocol=LLMClientProtocol.OPENAI,
                api_key="sk-1234567890",
                base_url="https://api.openrouter.com/v1",
                is_azure=False,
                azure_api_version="2023-03-15-preview",
            ),
        ],
        model_list=[
            ModelConfig(
                model_name="gpt-5",
                provider="openai",
                model_params=LLMConfigModelParameter(
                    model="gpt-5-2025-08-07",
                    temperature=1.0,
                    max_tokens=8192,
                    verbosity="medium",
                    reasoning=Reasoning(effort="high", summary="auto"),
                ),
            ),
            ModelConfig(
                model_name="sonnet-4",
                provider="openrouter",
                model_params=LLMConfigModelParameter(
                    model="anthropic/claude-sonnet-4",
                    temperature=1.0,
                    max_tokens=8192,
                    thinking=Thinking(type="enabled", budget_tokens=1024),
                    provider_routing=OpenRouterProviderRouting(
                        sort="throughput",
                    ),
                    plugins=[
                        OpenRouterPlugin(
                            id="web",
                        )
                    ],
                ),
            ),
        ],
    )


def load_config() -> Config:
    if not config_path.exists():
        log(f"Config file not found: {config_path}")
        example_config = get_example_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_dict = example_config.model_dump(mode="json", exclude_none=True)
        _ = config_path.write_text(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))
        log(f"Example config created at: {config_path}")
        log("[bold]Please edit the config file to set up your models[/bold]")
        return example_config

    config_yaml = config_path.read_text()
    config_dict = yaml.safe_load(config_yaml)
    config = Config.model_validate(config_dict)
    return config
