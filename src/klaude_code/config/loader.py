"""Config loading, saving, and example generation."""

from __future__ import annotations

import difflib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

import klaude_code.config.config as _schema
from klaude_code.auth import base as _auth_base
from klaude_code.auth.env import get_auth_env
from klaude_code.config.builtin_config import SUPPORTED_API_KEYS, get_builtin_config
from klaude_code.config.merge import merge_configs
from klaude_code.log import DebugType, log, log_debug
from klaude_code.protocol import llm_param


class ConfigValidationError(ValueError):
    """Raised when the user config file fails schema or YAML validation."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(message)


def _format_error_loc(loc: tuple[Any, ...]) -> str:
    """Format a pydantic error location as ``provider_list[2].provider_name``."""
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)


def _suggest_missing_field_typo(missing_field: str, input_value: Any) -> str | None:
    """Suggest a likely typo when a required field is missing but a similar key exists."""
    if not isinstance(input_value, dict):
        return None
    unknown_keys = [key for key in input_value if isinstance(key, str)]
    matches = difflib.get_close_matches(missing_field, unknown_keys, n=1, cutoff=0.6)
    if not matches:
        return None
    return f"did you mean '{missing_field}'? (found '{matches[0]}')"


def format_config_validation_error(path: Path, exc: ValidationError) -> str:
    """Turn a pydantic ValidationError into a concise, user-facing message."""
    lines = [f"Invalid config file: {path}", ""]
    for err in exc.errors():
        loc = _format_error_loc(tuple(err["loc"]))
        msg = err["msg"]
        lines.append(f"  • {loc}: {msg}" if loc else f"  • {msg}")

        input_value = err.get("input")
        if err.get("type") == "missing":
            suggestion = _suggest_missing_field_typo(str(err["loc"][-1]), input_value)
            if suggestion:
                lines.append(f"    Hint: {suggestion}")
        elif input_value is not None and not isinstance(input_value, (dict, list)):
            lines.append(f"    Got: {input_value!r}")

    lines.extend(["", "Fix the file and try again, or run: klaude conf"])
    return "\n".join(lines)


def get_example_config() -> _schema.UserConfig:
    """Generate example config for user reference (will be commented out)."""
    return _schema.UserConfig(
        main_model="opus",
        fast_model=["haiku", "gemini-flash", "gpt-5-nano"],
        compact_model=["gemini-flash", "haiku"],
        sub_agent_models={"general-purpose": "sonnet", "finder": "haiku"},
        provider_list=[
            _schema.UserProviderConfig(
                provider_name="my-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${MY_API_KEY}",
                base_url="https://api.example.com/v1",
                model_list=[
                    _schema.ModelConfig(
                        model_name="my-model",
                        model_alias=["my-model-legacy"],
                        model_id="model-id-from-provider",
                        max_tokens=16000,
                        context_limit=200000,
                        cost=llm_param.Cost(
                            input=1,
                            output=10,
                            cache_read=0.1,
                        ),
                    ),
                ],
            ),
        ],
    )


def create_example_config() -> bool:
    """Create example config file if it doesn't exist.

    Returns:
        True if file was created, False if it already exists.
    """
    if _schema.example_config_path.exists():
        return False

    example_config = get_example_config()
    _schema.example_config_path.parent.mkdir(parents=True, exist_ok=True)
    config_dict = example_config.model_dump(mode="json", exclude_none=True)

    yaml_str = yaml.dump(config_dict, default_flow_style=False, sort_keys=False) or ""
    header = (
        "# Example configuration for klaude-code\n"
        "# Copy this file to klaude-config.yaml and modify as needed.\n"
        "# Run `klaude agents` to see available models.\n"
        "# Tip: you can pick a provider explicitly with `model@provider` (e.g. `sonnet@openrouter`).\n"
        "# If you omit `@provider` (e.g. `sonnet`), klaude picks the first configured provider with credentials.\n"
        "#\n"
        "# Built-in providers (anthropic, openai, openrouter, deepseek) are available automatically.\n"
        "# Just set the corresponding API key environment variable to use them.\n\n"
    )
    _schema.example_config_path.write_text(header + yaml_str)
    return True


def _load_user_config() -> _schema.UserConfig | None:
    """Load user config from disk. Returns None if file doesn't exist or is empty."""
    if not _schema.config_path.exists():
        return None

    config_yaml = _schema.config_path.read_text()
    try:
        config_dict = yaml.safe_load(config_yaml)
    except yaml.YAMLError as e:
        message = (
            f"Invalid config file: {_schema.config_path}\n"
            f"\n"
            f"  • YAML parse error: {e}\n"
            f"\n"
            f"Fix the file and try again, or run: klaude conf"
        )
        raise ConfigValidationError(_schema.config_path, message) from e

    if config_dict is None:
        return None

    try:
        return _schema.UserConfig.model_validate(config_dict)
    except ValidationError as e:
        message = format_config_validation_error(_schema.config_path, e)
        raise ConfigValidationError(_schema.config_path, message) from e


def load_user_config_from_disk() -> _schema.UserConfig | None:
    """Read the user config file directly, bypassing the process-wide cache.

    Used by ``Config.save`` to merge into the current file instead of
    overwriting it with a possibly stale in-memory snapshot.

    Raises:
        ConfigValidationError: the file exists but is not valid.
    """
    return _load_user_config()


_LOAD_ATTEMPTS = 3
"""Read attempts before accepting a config parsed while its file kept changing."""


def _load_config_uncached() -> _schema.Config:
    """Load and merge builtin + user config. Always returns a valid Config.

    A writer that truncates before rewriting -- a plain ``write_text``, or an
    editor that writes in place -- can be caught mid-write, which parses as a
    partial config. Compare the file stamps around the read and retry, so the
    cache never keeps half a file as if it were the current one.
    """
    builtin_config = get_builtin_config()
    for _ in range(_LOAD_ATTEMPTS - 1):
        before = _fingerprint_now()
        user_config = _load_user_config()
        if before == _fingerprint_now():
            return merge_configs(user_config, builtin_config)
    return merge_configs(_load_user_config(), builtin_config)


@lru_cache(maxsize=1)
def _load_config_cached() -> _schema.Config:
    return _load_config_uncached()


type _FileStamp = tuple[int, int] | None
"""``(st_mtime_ns, st_size)`` of one config input, or None when it does not exist."""

type _ConfigFingerprint = tuple[Path, _FileStamp, Path, _FileStamp]
"""What the cached config was built from: the two input files and their stamps."""


# Fingerprint of the files the cached config was built from, and a counter bumped
# on every reload that picked up a change. Both are guarded by `_reload_lock`,
# which also serializes reloads so two threads cannot clear the cache twice.
_reload_lock = threading.Lock()
_cached_fingerprint: _ConfigFingerprint | None = None
_cached_config_path: Path | None = None
_config_revision = 0
# The last successfully loaded config's user-visible fields, the state clients
# have been told about, and the most recent reload nobody has been told about yet.
_last_snapshot: _ConfigSnapshot | None = None
_reported_snapshot: _ConfigSnapshot | None = None
_pending_reload: ConfigReload | None = None


def _stamp(path: Path) -> _FileStamp:
    """Read one file's identity without opening it."""
    try:
        stat = path.stat()
    except OSError:
        # Missing, or unreadable: either way the loader cannot see the file.
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _fingerprint_now() -> _ConfigFingerprint:
    """Snapshot every file the merged config is parsed from.

    The user config is the main input; ``klaude-auth.json`` is included because
    its ``env`` section resolves ``${ENV_VAR}`` api_keys, so storing a key
    there changes which models are available.
    """
    return (
        _schema.config_path,
        _stamp(_schema.config_path),
        _auth_base.KLAUDE_AUTH_FILE,
        _stamp(_auth_base.KLAUDE_AUTH_FILE),
    )


def _refresh_cached_fingerprint(config: _schema.Config | None = None) -> None:
    """Record the files the cached config was just (re)built from.

    ``config`` also updates the snapshot that reload summaries compare against.
    A caller that only re-stamps -- a process writing its own config -- passes
    nothing and leaves the last loaded snapshot in place.
    """
    global _cached_fingerprint, _cached_config_path, _last_snapshot
    _cached_fingerprint = _fingerprint_now()
    _cached_config_path = _schema.config_path
    if config is not None:
        _last_snapshot = _snapshot_config(config)


def _revision() -> int:
    with _reload_lock:
        return _config_revision


def _cached_config_or_none() -> _schema.Config | None:
    """The cached config, without loading one that is not there."""
    try:
        return _load_config_cached()
    except ValueError:
        return None


def config_revision() -> int:
    """Monotonic counter of config reloads this process observed.

    Bumped once per reload that picked up an on-disk change. A client that
    writes its own config does not bump it, so an unchanged value means the
    running process and the caller see the same revision.
    """
    return _revision()


def _reload_config() -> tuple[_schema.Config, int]:
    """Drop the cache, load from disk, and record the reload. Caller holds the lock."""
    global _config_revision, _pending_reload, _reported_snapshot
    # A cached instance built from another path (a test, or a different HOME)
    # describes a different file: there is nothing to compare against, and any
    # notice left over from it is not about this config.
    same_path = _cached_config_path == _schema.config_path
    # Summarize against the state clients were last told about, not the last
    # state on disk: two edits before the next poll must describe one change
    # from what the client actually saw.
    before = (_reported_snapshot or _last_snapshot) if same_path else None
    _load_config_cached.cache_clear()
    try:
        config = _load_config_cached()
    except ValueError:
        # A broken edit: re-stamp so neither the next call nor the poll loop
        # retries until the file changes again. The next call still raises,
        # because a failed load leaves nothing cached.
        _load_config_cached.cache_clear()
        _refresh_cached_fingerprint()
        raise
    _config_revision += 1
    _refresh_cached_fingerprint(config)
    if before is None:
        # A first load -- of this file, or after the config path moved: this is
        # the baseline every client starts from, so there is nothing to announce.
        _pending_reload = None
        _reported_snapshot = _last_snapshot
    elif _last_snapshot is not None:
        # Recorded here, not by whoever noticed the file: a reload triggered by
        # any caller (the reload endpoint, a socket handshake, the runtime) is
        # announced exactly once by `check_config_change`.
        _pending_reload = ConfigReload(
            revision=_config_revision,
            summary=_summarize_reload(before, _last_snapshot),
        )
    return config, _config_revision


class _LoadConfig:
    """Callable wrapper for load_config that exposes cache_clear."""

    def __call__(self) -> _schema.Config:
        """Load config from disk (builtin + user merged).

        Picks up on-disk edits by itself: the cache is dropped as soon as the
        config files' stamps differ from the ones the cached copy was built
        from, so no explicit ``cache_clear`` is needed after editing them.
        A process that writes its own config keeps the cached instance (see
        :meth:`sync_fingerprint`), so edits it made in memory survive.

        Always returns a valid Config. Use
        ``config.iter_model_entries(only_available=True, include_disabled=False)``
        to check if any models are actually usable.
        """
        with _reload_lock:
            if self._is_stale():
                return _reload_config()[0]
        try:
            return _load_config_cached()
        except ValueError:
            _load_config_cached.cache_clear()
            raise

    def _is_stale(self) -> bool:
        """Whether the cached config was built from files that have since changed."""
        if _cached_fingerprint is None:
            return True
        if _cached_config_path != _schema.config_path:
            # The config path itself moved (tests, or a different HOME): the
            # cached instance describes another file.
            return True
        return _cached_fingerprint != _fingerprint_now()

    def cache_clear(self) -> None:
        """Clear the config cache, forcing a fresh load on next call."""
        _load_config_cached.cache_clear()

    def sync_fingerprint(self) -> None:
        """Re-stamp the config files after this process wrote them.

        ``Config.save`` calls this so its own write is not mistaken for an
        external edit: without it the next ``load_config`` would rebuild the
        merged instance and drop in-memory changes that were not saved yet.
        """
        with _reload_lock:
            _refresh_cached_fingerprint(_cached_config_or_none())


load_config = _LoadConfig()


@dataclass(frozen=True, slots=True)
class ConfigReload:
    """One reload that picked up an on-disk change."""

    revision: int
    #: One line for the user, e.g. ``main model: opus -> sonnet``.
    summary: str


@dataclass(frozen=True, slots=True)
class _ConfigSnapshot:
    """The user-visible config fields a reload summary compares."""

    main_model: str | None
    fast_model: str | None
    compact_model: str | None
    sub_agent_models: dict[str, str]


def _snapshot_config(config: _schema.Config) -> _ConfigSnapshot:
    return _ConfigSnapshot(
        main_model=_schema.format_model_preference(config.main_model),
        fast_model=_schema.format_model_preference(config.fast_model),
        compact_model=_schema.format_model_preference(config.compact_model),
        sub_agent_models={
            role: preference
            for role, value in config.sub_agent_models.items()
            if (preference := _schema.format_model_preference(value)) is not None
        },
    )


def _summarize_reload(before: _ConfigSnapshot, after: _ConfigSnapshot) -> str:
    """Describe what a reload changed, for the broadcast event."""
    changes: list[str] = []
    for label, previous, current in (
        ("main model", before.main_model, after.main_model),
        ("fast model", before.fast_model, after.fast_model),
        ("compact model", before.compact_model, after.compact_model),
    ):
        if previous != current:
            changes.append(f"{label}: {previous or 'none'} -> {current or 'none'}")
    for role in sorted(set(before.sub_agent_models) | set(after.sub_agent_models)):
        previous = before.sub_agent_models.get(role)
        current = after.sub_agent_models.get(role)
        if previous != current:
            changes.append(f"{role} model: {previous or 'main'} -> {current or 'main'}")
    if not changes:
        return "no model changes"
    return "; ".join(changes)


def check_config_change() -> ConfigReload | None:
    """Report a config reload that no client has been told about yet.

    Reloads triggered elsewhere -- the reload endpoint, a socket handshake, a
    runtime call -- are reported here too, because the reload records itself
    rather than relying on whoever happens to read the file first. Never raises
    on an invalid file: the caller is a poll loop that must survive a
    half-written edit, and the next successful read reports the change.
    """
    global _pending_reload, _reported_snapshot
    with _reload_lock:
        if _pending_reload is None and load_config._is_stale():
            try:
                _reload_config()
            except Exception as exc:
                log_debug(f"[config] reload failed: {exc}", debug_type=DebugType.GENERAL)
        notice = _pending_reload
        _pending_reload = None
        if notice is not None:
            # Clients are being told about this state: the next summary starts here.
            _reported_snapshot = _last_snapshot
    return notice


DEFAULT_CONFIG_WATCH_INTERVAL_S = 1.0


class ConfigWatcher:
    """Daemon poll loop that reloads the config when the files change.

    A plain ``stat`` per tick: the files are local and tiny, so polling costs
    less than a dependency on an OS file watcher. ``on_reload`` runs on this
    thread and must not block for long.
    """

    def __init__(
        self,
        on_reload: Callable[[ConfigReload], None],
        *,
        interval_s: float = DEFAULT_CONFIG_WATCH_INTERVAL_S,
    ) -> None:
        self._on_reload = on_reload
        self._interval_s = interval_s
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        thread = threading.Thread(target=self._loop, name="klaude-config-watcher", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self, *, timeout_s: float = 2.0) -> None:
        """Ask the loop to end and wait briefly for it."""
        self._stopped.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_s)
        self._thread = None

    def _loop(self) -> None:
        while not self._stopped.wait(self._interval_s):
            try:
                reload_event = check_config_change()
            except Exception as exc:  # the poll loop must outlive a bad edit
                log_debug(f"[config] watcher error: {exc}", debug_type=DebugType.GENERAL)
                continue
            if reload_event is None:
                continue
            try:
                self._on_reload(reload_event)
            except Exception as exc:
                log_debug(f"[config] watcher callback failed: {exc}", debug_type=DebugType.GENERAL)


def start_config_watcher(
    on_reload: Callable[[ConfigReload], None],
    *,
    interval_s: float = DEFAULT_CONFIG_WATCH_INTERVAL_S,
) -> ConfigWatcher:
    """Start a :class:`ConfigWatcher` and return it, so the caller can stop it."""
    watcher = ConfigWatcher(on_reload, interval_s=interval_s)
    watcher.start()
    return watcher


def print_no_available_models_hint() -> None:
    """Print helpful message when no models are available due to missing API keys."""
    log("No available models. Configure an API key using one of these methods:")
    log("")
    log("Option 1: Use klaude auth login")
    # Use first word of name for brevity
    names = [k.name.split()[0].lower() for k in SUPPORTED_API_KEYS]
    log(f"  klaude auth login <provider>  (providers: {', '.join(names)})")
    log("")
    log("Option 2: Set environment variables")
    max_len = max(len(k.env_var) for k in SUPPORTED_API_KEYS)
    for key_info in SUPPORTED_API_KEYS:
        current_value = os.environ.get(key_info.env_var) or get_auth_env(key_info.env_var)
        if current_value:
            log(f"  {key_info.env_var:<{max_len}}  (set)")
        else:
            log(f"  {key_info.env_var:<{max_len}}  {key_info.description}")
    log("")
    log(f"Or add custom providers in: {_schema.config_path}")
