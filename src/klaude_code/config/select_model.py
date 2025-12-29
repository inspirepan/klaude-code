from dataclasses import dataclass

from klaude_code.config.config import ModelEntry, load_config, print_no_available_models_hint
from klaude_code.trace import log


def _normalize_model_key(value: str) -> str:
    """Normalize a model identifier for loose matching.

    This enables aliases like:
    - gpt52 -> gpt-5.2
    - gpt5.2 -> gpt-5.2

    Strategy: case-fold + keep only alphanumeric characters.
    """

    return "".join(ch for ch in value.casefold() if ch.isalnum())


@dataclass
class ModelMatchResult:
    """Result of model matching.

    Attributes:
        matched_model: The single matched model name, or None if ambiguous/no match.
        filtered_models: List of filtered models for interactive selection.
        filter_hint: The filter hint to show (original preferred value), or None.
        error_message: Error message if no models available, or None.
    """

    matched_model: str | None
    filtered_models: list[ModelEntry]
    filter_hint: str | None
    error_message: str | None = None


def match_model_from_config(preferred: str | None = None) -> ModelMatchResult:
    """Match model from config without interactive selection.

    If preferred is provided:
    - Exact match: returns matched_model
    - Single partial match (case-insensitive): returns matched_model
    - Multiple matches: returns filtered_models for interactive selection
    - No matches: returns all models with filter_hint=None

    Returns:
        ModelMatchResult with match state.
    """
    config = load_config()

    # Only show models from providers with valid API keys
    models: list[ModelEntry] = sorted(
        config.iter_model_entries(only_available=True), key=lambda m: m.model_name.lower()
    )

    if not models:
        print_no_available_models_hint()
        return ModelMatchResult(
            matched_model=None,
            filtered_models=[],
            filter_hint=None,
            error_message="No models available",
        )

    names: list[str] = [m.model_name for m in models]

    # Try to match preferred model name
    filter_hint = preferred
    if preferred and preferred.strip():
        preferred = preferred.strip()
        # Exact match
        if preferred in names:
            return ModelMatchResult(matched_model=preferred, filtered_models=models, filter_hint=None)

        preferred_lower = preferred.lower()
        # Case-insensitive exact match (model_name or model_params.model)
        exact_ci_matches = [
            m
            for m in models
            if preferred_lower == m.model_name.lower() or preferred_lower == (m.model_params.model or "").lower()
        ]
        if len(exact_ci_matches) == 1:
            return ModelMatchResult(
                matched_model=exact_ci_matches[0].model_name, filtered_models=models, filter_hint=None
            )

        # Normalized matching (e.g. gpt52 == gpt-5.2, gpt52 in gpt-5.2-2025-...)
        preferred_norm = _normalize_model_key(preferred)
        normalized_matches: list[ModelEntry] = []
        if preferred_norm:
            normalized_matches = [
                m
                for m in models
                if preferred_norm == _normalize_model_key(m.model_name)
                or preferred_norm == _normalize_model_key(m.model_params.model or "")
            ]
            if len(normalized_matches) == 1:
                return ModelMatchResult(
                    matched_model=normalized_matches[0].model_name, filtered_models=models, filter_hint=None
                )

            if not normalized_matches and len(preferred_norm) >= 4:
                normalized_matches = [
                    m
                    for m in models
                    if preferred_norm in _normalize_model_key(m.model_name)
                    or preferred_norm in _normalize_model_key(m.model_params.model or "")
                ]
                if len(normalized_matches) == 1:
                    return ModelMatchResult(
                        matched_model=normalized_matches[0].model_name, filtered_models=models, filter_hint=None
                    )

        # Partial match (case-insensitive) on model_name or model_params.model.
        # If normalized matching found candidates (even if multiple), prefer those as the filter set.
        matches = normalized_matches or [
            m
            for m in models
            if preferred_lower in m.model_name.lower() or preferred_lower in (m.model_params.model or "").lower()
        ]
        if len(matches) == 1:
            return ModelMatchResult(matched_model=matches[0].model_name, filtered_models=models, filter_hint=None)
        if matches:
            # Multiple matches: filter the list for interactive selection
            return ModelMatchResult(matched_model=None, filtered_models=matches, filter_hint=filter_hint)
        else:
            # No matches: show all models without filter hint
            log(("No matching models found. Showing all models.", "yellow"))
            return ModelMatchResult(matched_model=None, filtered_models=models, filter_hint=None)

    return ModelMatchResult(matched_model=None, filtered_models=models, filter_hint=None)
