"""Which LLM errors advance the fallback chain instead of retrying the same model."""

from __future__ import annotations

import pytest

from klaude_code.agent.model_fallback import is_fallbackable_llm_error

# A provider can list a model and still refuse every request for it: OpenRouter
# serves a model through upstream providers that the account settings may exclude.
OPENROUTER_ALLOWED_PROVIDERS_404 = (
    "NotFoundError Error code: 404 - {'error': {'message': \"No allowed providers are available "
    "for the selected model. Providers serving openai/gpt-6.1-sol-20260929: azure, openai, but your "
    "account's allowed-providers setting permits only: reka, google-vertex, deepseek.\", 'code': 404}}"
)


@pytest.mark.parametrize(
    "error_message",
    [
        OPENROUTER_ALLOWED_PROVIDERS_404,
        "NotFoundError Error code: 404 - {'error': {'message': 'No endpoints found for openai/gpt-6.1-sol.'}}",
        "PermissionDeniedError Error code: 403 - This model is not available in your region.",
    ],
)
def test_provider_side_model_unavailability_advances_the_chain(error_message: str) -> None:
    assert is_fallbackable_llm_error(error_message)


def test_generic_request_error_is_not_fallbackable() -> None:
    # A malformed request says nothing about the model, so switching models would
    # hide the bug instead of recovering from it.
    assert not is_fallbackable_llm_error("BadRequestError Error code: 400 - invalid request payload")
