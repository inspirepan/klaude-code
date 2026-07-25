from klaude_code.prompts.away_summary import (
    AWAY_SUMMARY_SYSTEM_PROMPT,
    AWAY_SUMMARY_USER_PROMPT,
)


def test_away_summary_prompt_requires_the_user_language() -> None:
    for prompt in (AWAY_SUMMARY_SYSTEM_PROMPT, AWAY_SUMMARY_USER_PROMPT):
        assert "if the user wrote chinese, reply in chinese" in prompt.lower()
        assert "assistant" in prompt
        assert "tool" in prompt
