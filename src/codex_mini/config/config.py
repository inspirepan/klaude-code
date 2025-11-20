import asyncio
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, model_validator

from codex_mini.core.subagent import iter_sub_agent_profiles
from codex_mini.protocol.llm_parameter import (
    LLMClientProtocol,
    LLMConfigModelParameter,
    LLMConfigParameter,
    LLMConfigProviderParameter,
    OpenRouterProviderRouting,
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
    subagent_models: dict[str, str] = Field(default_factory=dict)
    theme: str | None = None
    user_skills_dir: str = "~/.claude/skills"
    project_skills_dir: str = "./.claude/skills"

    @model_validator(mode="before")
    @classmethod
    def _normalize_subagent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        raw_val: Any = data.get("subagent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, str] = {}
        key_map = {p.config_key.lower(): p.config_key for p in iter_sub_agent_profiles()}
        for key, value in dict(raw_models).items():
            canonical = key_map.get(str(key).lower(), str(key))
            normalized[canonical] = str(value)
        data["subagent_models"] = normalized
        return data

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
        subagent_models={"Explore": "sonnet-4"},
        provider_list=[
            LLMConfigProviderParameter(
                provider_name="openai",
                protocol=LLMClientProtocol.RESPONSES,
                api_key="sk-1234567890",
                base_url="https://api.openai.com/v1",
                is_azure=False,
                azure_api_version="2025-04-01-preview",
            ),
            LLMConfigProviderParameter(
                provider_name="openrouter",
                protocol=LLMClientProtocol.OPENROUTER,
                api_key="sk-1234567890",
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
                    thinking=Thinking(
                        reasoning_effort="high", reasoning_summary="auto", type="disabled", budget_tokens=None
                    ),
                    context_limit=400000,
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
                    context_limit=200000,
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
