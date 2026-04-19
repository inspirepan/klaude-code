from dataclasses import dataclass

from klaude_code.config.config import ModelEntry, load_config, normalize_provider_name, print_no_available_models_hint


def _normalize_model_key(value: str) -> str:
    """Normalize a model identifier for loose matching.

    This enables aliases like:
    - gpt52 -> gpt-5.2
    - gpt5.2 -> gpt-5.2

    Strategy: case-fold + keep only alphanumeric characters.
    """

    return "".join(ch for ch in value.casefold() if ch.isalnum())

def _matches_query(value: str, query: str) -> bool:
    value_lower = value.casefold()
    query_lower = query.casefold()
    if query_lower in value_lower:
        return True

    query_norm = _normalize_model_key(query)
    if not query_norm:
        return False
    return query_norm in _normalize_model_key(value)

def _match_provider_qualified_query(models: list[ModelEntry], preferred: str) -> list[ModelEntry]:
    if "@" not in preferred:
        return []

    model_query, provider_query = preferred.rsplit("@", 1)
    model_query = model_query.strip()
    provider_query = provider_query.strip()
    if not model_query or not provider_query:
        return []

    provider_queries = {provider_query}
    normalized_provider = normalize_provider_name(provider_query)
    if normalized_provider:
        provider_queries.add(normalized_provider)

    return [
        model
        for model in models
        if any(_matches_query(model.provider, query) for query in provider_queries)
        and (_matches_query(model.model_name, model_query) or _matches_query(model.model_id or "", model_query))
    ]

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
    - No matches: returns an empty filtered_models list with filter_hint=preferred

    Returns:
        ModelMatchResult with match state.
    """
    config = load_config()

    # Keep config-defined provider/model order so all pickers stay consistent.
    models: list[ModelEntry] = config.iter_model_entries(only_available=True, include_disabled=False)

    if not models:
        print_no_available_models_hint()
        return ModelMatchResult(
            matched_model=None,
            filtered_models=[],
            filter_hint=None,
            error_message="No models available",
        )

    selectors: list[str] = [m.selector for m in models]

    # Try to match preferred model name
    filter_hint = preferred
    if preferred and preferred.strip():
        preferred = preferred.strip()

        # Exact match on selector (e.g. sonnet@openrouter)
        if preferred in selectors:
            return ModelMatchResult(matched_model=preferred, filtered_models=models, filter_hint=None)

        # Exact match on base model name (e.g. sonnet)
        exact_base_matches = [m for m in models if m.model_name == preferred]
        if len(exact_base_matches) == 1:
            return ModelMatchResult(
                matched_model=exact_base_matches[0].selector,
                filtered_models=models,
                filter_hint=None,
            )
        if len(exact_base_matches) > 1:
            return ModelMatchResult(matched_model=None, filtered_models=exact_base_matches, filter_hint=filter_hint)

        preferred_lower = preferred.lower()
        # Case-insensitive exact match (selector/model_name/model_id)
        exact_ci_matches = [
            m
            for m in models
            if preferred_lower == m.selector.lower()
            or preferred_lower == m.model_name.lower()
            or preferred_lower == (m.model_id or "").lower()
        ]
        if len(exact_ci_matches) == 1:
            return ModelMatchResult(
                matched_model=exact_ci_matches[0].selector,
                filtered_models=models,
                filter_hint=None,
            )

        provider_qualified_matches = _match_provider_qualified_query(models, preferred)
        if len(provider_qualified_matches) == 1:
            return ModelMatchResult(
                matched_model=provider_qualified_matches[0].selector,
                filtered_models=models,
                filter_hint=None,
            )
        if provider_qualified_matches:
            return ModelMatchResult(
                matched_model=None,
                filtered_models=provider_qualified_matches,
                filter_hint=filter_hint,
            )

        # Normalized matching (e.g. gpt52 == gpt-5.2, gpt52 in gpt-5.2-2025-...)
        # Only match selector/model_name exactly; model_id is checked via substring match below
        preferred_norm = _normalize_model_key(preferred)
        normalized_matches: list[ModelEntry] = []
        if preferred_norm:
            normalized_matches = [
                m
                for m in models
                if preferred_norm == _normalize_model_key(m.selector)
                or preferred_norm == _normalize_model_key(m.model_name)
            ]
            if len(normalized_matches) == 1:
                return ModelMatchResult(
                    matched_model=normalized_matches[0].selector,
                    filtered_models=models,
                    filter_hint=None,
                )

            if not normalized_matches and len(preferred_norm) >= 4:
                normalized_matches = [
                    m
                    for m in models
                    if preferred_norm in _normalize_model_key(m.selector)
                    or preferred_norm in _normalize_model_key(m.model_name)
                    or preferred_norm in _normalize_model_key(m.model_id or "")
                ]
                if len(normalized_matches) == 1:
                    return ModelMatchResult(
                        matched_model=normalized_matches[0].selector,
                        filtered_models=models,
                        filter_hint=None,
                    )

        # Partial match (case-insensitive) on model_name or model_id.
        # If normalized matching found candidates (even if multiple), prefer those as the filter set.
        matches = normalized_matches or [
            m
            for m in models
            if preferred_lower in m.selector.lower()
            or preferred_lower in m.model_name.lower()
            or preferred_lower in (m.model_id or "").lower()
        ]
        if len(matches) == 1:
            return ModelMatchResult(matched_model=matches[0].selector, filtered_models=models, filter_hint=None)
        if matches:
            return ModelMatchResult(matched_model=None, filtered_models=matches, filter_hint=filter_hint)
        return ModelMatchResult(matched_model=None, filtered_models=[], filter_hint=filter_hint)

    return ModelMatchResult(matched_model=None, filtered_models=models, filter_hint=None)
