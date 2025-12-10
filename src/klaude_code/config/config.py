import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles
from klaude_code.trace import log

config_path = Path.home() / ".klaude" / "klaude-config.yaml"


class ModelConfig(BaseModel):
    model_name: str
    provider: str
    model_params: llm_param.LLMConfigModelParameter


class Config(BaseModel):
    provider_list: list[llm_param.LLMConfigProviderParameter]
    model_list: list[ModelConfig]
    main_model: str
    sub_agent_models: dict[str, str] = Field(default_factory=dict)
    theme: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_sub_agent_models(cls, data: dict[str, Any]) -> dict[str, Any]:
        raw_val: Any = data.get("sub_agent_models") or {}
        raw_models: dict[str, Any] = cast(dict[str, Any], raw_val) if isinstance(raw_val, dict) else {}
        normalized: dict[str, str] = {}
        key_map = {p.name.lower(): p.name for p in iter_sub_agent_profiles()}
        for key, value in dict(raw_models).items():
            canonical = key_map.get(str(key).lower(), str(key))
            normalized[canonical] = str(value)
        data["sub_agent_models"] = normalized
        return data

    def get_main_model_config(self) -> llm_param.LLMConfigParameter:
        return self.get_model_config(self.main_model)

    def get_model_config(self, model_name: str) -> llm_param.LLMConfigParameter:
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

        return llm_param.LLMConfigParameter(
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
            yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
            _ = config_path.write_text(str(yaml_content or ""))

        await asyncio.to_thread(_save_config)


def get_example_config() -> Config:
    return Config(
        main_model="opus",
        sub_agent_models={"explore": "haiku", "oracle": "gpt-5.1", "webagent": "haiku", "task": "opus"},
        provider_list=[
            llm_param.LLMConfigProviderParameter(
                provider_name="openai",
                protocol=llm_param.LLMClientProtocol.RESPONSES,
                api_key="your-openai-api-key",
                base_url="https://api.openai.com/v1",
            ),
            llm_param.LLMConfigProviderParameter(
                provider_name="openrouter",
                protocol=llm_param.LLMClientProtocol.OPENROUTER,
                api_key="your-openrouter-api-key",
            ),
            llm_param.LLMConfigProviderParameter(
                provider_name="anthropic",
                protocol=llm_param.LLMClientProtocol.ANTHROPIC,
                api_key="your-anthropic-api-key",
            ),
        ],
        model_list=[
            ModelConfig(
                model_name="gpt-5.1",
                provider="openai",
                model_params=llm_param.LLMConfigModelParameter(
                    model="gpt-5.1-2025-11-13",
                    verbosity="medium",
                    thinking=llm_param.Thinking(
                        reasoning_effort="high",
                        reasoning_summary="auto",
                    ),
                    context_limit=400000,
                ),
            ),
            ModelConfig(
                model_name="opus",
                provider="anthropic",
                model_params=llm_param.LLMConfigModelParameter(
                    model="claude-opus-4-5-20251101",
                    verbosity="high",
                    thinking=llm_param.Thinking(
                        type="enabled",
                        budget_tokens=31999,
                    ),
                    context_limit=200000,
                ),
            ),
            ModelConfig(
                model_name="haiku",
                provider="openrouter",
                model_params=llm_param.LLMConfigModelParameter(
                    model="anthropic/claude-haiku-4.5",
                    max_tokens=32000,
                    provider_routing=llm_param.OpenRouterProviderRouting(
                        sort="throughput",
                    ),
                    context_limit=200000,
                ),
            ),
        ],
    )


def _load_config_uncached() -> Config | None:
    if not config_path.exists():
        log(f"Config file not found: {config_path}")
        example_config = get_example_config()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_dict = example_config.model_dump(mode="json", exclude_none=True)

        # Comment out all example config lines
        yaml_str = yaml.dump(config_dict, default_flow_style=False, sort_keys=False) or ""
        commented_yaml = "\n".join(f"# {line}" if line.strip() else "#" for line in yaml_str.splitlines())
        _ = config_path.write_text(commented_yaml)

        log(f"Example config created at: {config_path}")
        log("Please edit the config file to set up your models", style="yellow bold")
        return None

    config_yaml = config_path.read_text()
    config_dict = yaml.safe_load(config_yaml)

    if config_dict is None:
        log(f"Config file is empty or all commented: {config_path}", style="red bold")
        log("Please edit the config file to set up your models", style="yellow bold")
        return None

    try:
        config = Config.model_validate(config_dict)
    except ValidationError as e:
        log(f"Invalid config file: {config_path}", style="red bold")
        log(str(e), style="red")
        raise ValueError(f"Invalid config file: {config_path}") from e

    return config


@lru_cache(maxsize=1)
def _load_config_cached() -> Config | None:
    return _load_config_uncached()


def load_config() -> Config | None:
    """Load config from disk, caching only successful parses.

    Returns:
        Config object on success, or None when the config is missing/empty/commented out.
    """

    try:
        config = _load_config_cached()
    except ValueError:
        _load_config_cached.cache_clear()
        raise

    if config is None:
        _load_config_cached.cache_clear()
    return config


# Expose cache control for tests and callers that need to invalidate the cache.
load_config.cache_clear = _load_config_cached.cache_clear  # type: ignore[attr-defined]
