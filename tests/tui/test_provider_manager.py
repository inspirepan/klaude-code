from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from klaude_code.config.config import (
    Config,
    ProviderConfig,
    WebSearchConfig,
    WebSearchProviderConfig,
    default_web_search_config,
)
from klaude_code.protocol.llm_param import LLMClientProtocol
from klaude_code.tui.command import provider_manager
from klaude_code.tui.command.provider_manager import SearchProviderState


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


class TestBuildSearchProviderStates:
    def test_enabled_first_in_chain_order_then_disabled(self, monkeypatch) -> None:
        monkeypatch.setattr("klaude_code.config.config.get_auth_env", lambda _name: None)
        config = Config(
            web_search=WebSearchConfig(
                providers=[
                    WebSearchProviderConfig(provider="openai", model="gpt-5.6-terra"),
                    WebSearchProviderConfig(provider="brave"),
                ]
            )
        )

        states = provider_manager.build_search_provider_states(config)

        assert [(s.name, s.enabled) for s in states] == [
            ("openai", True),
            ("brave", True),
            ("exa", False),
            ("deepseek", False),
        ]
        assert states[0].model == "gpt-5.6-terra"

    def test_has_api_key_reflects_resolution(self, monkeypatch) -> None:
        monkeypatch.setattr("klaude_code.config.config.get_auth_env", lambda _name: None)
        monkeypatch.setattr(
            "klaude_code.tui.command.provider_manager.resolve_api_key",
            lambda value: "key" if value == "${BRAVE_API_KEY}" else None,
        )
        config = Config()  # default chain: exa > brave > deepseek > openai

        states = provider_manager.build_search_provider_states(config)

        assert [(s.name, s.has_api_key) for s in states] == [
            ("exa", False),
            ("brave", True),
            ("deepseek", False),
            ("openai", False),
        ]


class TestBuildWebSearchConfig:
    def test_preserves_merged_fields_for_selected_names(self, monkeypatch) -> None:
        monkeypatch.setattr("klaude_code.config.config.get_auth_env", lambda _name: None)
        config = Config(
            web_search=WebSearchConfig(
                providers=[
                    WebSearchProviderConfig(
                        provider="deepseek",
                        api_key="${DEEPSEEK_API_KEY}",
                        base_url="https://proxy.example.com/anthropic",
                        model="deepseek-v4-pro",
                    ),
                    WebSearchProviderConfig(provider="brave", api_key="${BRAVE_API_KEY}"),
                ]
            )
        )

        result = provider_manager.build_web_search_config(config, ["brave", "deepseek"])

        assert [(p.provider, p.model) for p in result.providers] == [("brave", None), ("deepseek", "deepseek-v4-pro")]
        assert result.providers[1].base_url == "https://proxy.example.com/anthropic"

    def test_falls_back_to_builtin_fields_for_names_outside_current_chain(self, monkeypatch) -> None:
        config = Config(web_search=WebSearchConfig(providers=[WebSearchProviderConfig(provider="brave")]))

        result = provider_manager.build_web_search_config(config, ["exa", "brave"])

        builtin_exa = default_web_search_config().providers[0]
        assert result.providers[0].provider == "exa"
        assert result.providers[0].api_key == builtin_exa.api_key


class TestInteractiveKeyBindings:
    """Drive the interactive app through a pipe to lock in key-binding behavior."""

    def _search_states(self) -> list[SearchProviderState]:
        return [
            SearchProviderState(name="exa", enabled=True, has_api_key=True, model=None),
            SearchProviderState(name="brave", enabled=True, has_api_key=True, model=None),
            SearchProviderState(name="deepseek", enabled=True, has_api_key=True, model="deepseek-v4-flash"),
            SearchProviderState(name="openai", enabled=False, has_api_key=False, model="gpt-5.6-luna"),
        ]

    def _run_with_keys(self, keys: str) -> provider_manager.ManageProvidersResult | None:
        with create_pipe_input() as inp:
            inp.send_text(keys)
            return provider_manager.manage_providers_interactive(
                [], self._search_states(), _input=inp, _output=DummyOutput()
            )

    def test_alt_down_reorders_instead_of_exiting(self) -> None:
        """Regression: an eager lone-Escape binding used to cancel the dialog on Alt+arrows."""
        # Pointer starts on the first search row (exa): Alt+Down swaps exa/brave, "s" saves.
        result = self._run_with_keys("\x1b[1;3Bs")
        assert result is not None
        assert result.search_provider_names == ["brave", "exa", "deepseek"]

    def test_k_j_reorder_and_space_toggle(self) -> None:
        # J moves exa below brave (pointer follows), Space disables exa, s saves.
        result = self._run_with_keys("J s")
        assert result is not None
        assert result.search_provider_names == ["brave", "deepseek"]

    def test_lone_escape_still_cancels(self) -> None:
        result = self._run_with_keys("\x1b")
        assert result is None
