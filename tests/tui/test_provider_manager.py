from klaude_code.config.config import Config, ProviderConfig
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.tui.command import provider_manager


def _provider(name: str, api_key: str | None = None) -> ProviderConfig:
    return ProviderConfig(
        provider_name=name,
        protocol=LLMClientProtocol.OPENAI,
        api_key=api_key,
    )


def test_build_provider_states_hides_unconfigured_builtins(monkeypatch) -> None:
    builtin = Config(provider_list=[_provider("configured"), _provider("unconfigured")])
    monkeypatch.setattr(provider_manager, "get_builtin_config", lambda: builtin)
    config = Config(
        provider_list=[
            _provider("configured", "test-key"),
            _provider("unconfigured"),
            _provider("custom"),
        ]
    )

    states = provider_manager.build_provider_states(config)

    assert [(state.name, state.source) for state in states] == [
        ("configured", "builtin"),
        ("custom", "custom"),
    ]
