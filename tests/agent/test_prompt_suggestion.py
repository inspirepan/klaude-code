import unittest
from pathlib import Path

from klaude_code.agent.prompt_suggestion.prompt_suggestion import (
    _MAX_PARENT_UNCACHED_TOKENS,  # pyright: ignore[reportPrivateUsage]
    _filter_reason,  # pyright: ignore[reportPrivateUsage]
    _normalize,  # pyright: ignore[reportPrivateUsage]
    should_suggest,
)
from klaude_code.protocol import message
from klaude_code.protocol.models import Usage
from klaude_code.protocol.models.common import StopReason
from klaude_code.session.session import Session


def _assistant(*, stop_reason: StopReason = "stop", usage: Usage | None = None) -> message.AssistantMessage:
    return message.AssistantMessage(
        parts=[message.TextPart(text="hi")],
        response_id=None,
        stop_reason=stop_reason,
        usage=usage,
    )


def _user(text: str = "hello") -> message.UserMessage:
    return message.UserMessage(parts=[message.TextPart(text=text)])


class TestShouldSuggest(unittest.TestCase):
    """Guard chain: early conversation / last-response-error / cache cold."""

    def _session(self, items: list[message.HistoryEvent]) -> Session:
        sess = Session(id="s", work_dir=Path.cwd())
        sess.conversation_history = items
        return sess

    def test_early_conversation_with_one_assistant_turn(self) -> None:
        sess = self._session([_user(), _assistant()])
        self.assertEqual(should_suggest(sess), "early_conversation")

    def test_allows_with_two_assistant_turns(self) -> None:
        sess = self._session(
            [_user(), _assistant(), _user("again"), _assistant(usage=Usage(input_tokens=100, output_tokens=50))]
        )
        self.assertIsNone(should_suggest(sess))

    def test_skips_after_error_stop_reason(self) -> None:
        sess = self._session(
            [_user(), _assistant(), _user("again"), _assistant(stop_reason="error")]
        )
        self.assertEqual(should_suggest(sess), "last_response_error")

    def test_skips_after_aborted_stop_reason(self) -> None:
        sess = self._session(
            [_user(), _assistant(), _user("again"), _assistant(stop_reason="aborted")]
        )
        self.assertEqual(should_suggest(sess), "last_response_error")

    def test_hot_cache_allows(self) -> None:
        """99% cache hit: mostly read from cache, small fresh work → allow."""
        usage = Usage(
            input_tokens=51_000,  # total (includes cached+write per klaude convention)
            cached_tokens=50_500,
            cache_write_tokens=0,
            output_tokens=2_500,
        )
        sess = self._session([_user(), _assistant(), _user("again"), _assistant(usage=usage)])
        uncached_expected = (51_000 - 50_500) + 2_500
        self.assertLess(uncached_expected, _MAX_PARENT_UNCACHED_TOKENS)
        self.assertIsNone(should_suggest(sess))

    def test_cold_cache_skips(self) -> None:
        """First turn with no cache: large fresh work → skip."""
        usage = Usage(
            input_tokens=30_000,
            cached_tokens=0,
            cache_write_tokens=0,
            output_tokens=2_500,
        )
        sess = self._session([_user(), _assistant(), _user("again"), _assistant(usage=usage)])
        reason = should_suggest(sess)
        self.assertIsNotNone(reason)
        assert reason is not None
        self.assertTrue(reason.startswith("cache_cold"))

    def test_anthropic_raw_hot_cache_allows(self) -> None:
        """Hypothetical Anthropic-raw semantics (input_tokens = only-new).

        Klaude currently stores totals, but the normalization ``max(input,
        cached+cache_write)`` should keep this resilient if that convention
        ever changes.
        """
        usage = Usage(
            input_tokens=500,  # raw-semantics "only new"
            cached_tokens=50_500,  # cache read
            cache_write_tokens=0,
            output_tokens=2_500,
        )
        sess = self._session([_user(), _assistant(), _user("again"), _assistant(usage=usage)])
        self.assertIsNone(should_suggest(sess))


class TestNormalize(unittest.TestCase):
    def test_done_literal(self) -> None:
        self.assertIsNone(_normalize("[DONE]"))
        self.assertIsNone(_normalize(" [done] "))
        self.assertIsNone(_normalize("[ DONE ]"))

    def test_strips_quotes(self) -> None:
        self.assertEqual(_normalize('"run the tests"'), "run the tests")
        self.assertEqual(_normalize("“commit this”"), "commit this")

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(_normalize(""))
        self.assertIsNone(_normalize("   "))


class TestFilterReason(unittest.TestCase):
    def test_accepts_short_imperative(self) -> None:
        self.assertIsNone(_filter_reason("run the tests"))
        self.assertIsNone(_filter_reason("commit this"))

    def test_rejects_too_many_words(self) -> None:
        self.assertEqual(
            _filter_reason("one two three four five six seven eight nine ten eleven twelve thirteen"),
            "too_many_words",
        )

    def test_rejects_multiple_sentences(self) -> None:
        self.assertEqual(
            _filter_reason("do this. Then do that"),
            "multiple_sentences",
        )

    def test_rejects_formatting(self) -> None:
        self.assertEqual(_filter_reason("**do it**"), "has_formatting")
        self.assertEqual(_filter_reason("run\nthe tests"), "has_formatting")

    def test_rejects_evaluative(self) -> None:
        self.assertEqual(_filter_reason("looks good"), "evaluative")
        self.assertEqual(_filter_reason("thanks for the fix"), "evaluative")

    def test_rejects_assistant_voice(self) -> None:
        self.assertEqual(_filter_reason("Let me try that"), "assistant_voice")
        self.assertEqual(_filter_reason("I'll run it"), "assistant_voice")
        self.assertEqual(_filter_reason("Here's the plan"), "assistant_voice")


if __name__ == "__main__":
    unittest.main()
