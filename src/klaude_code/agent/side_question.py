"""`/btw` side question: a single-turn forked query beside the running task.

The user asks something while the main agent keeps working. The answer must not
change what the main agent sees, so this module only *reads* the session:

- The wire prefix is ``session.get_llm_history()`` — the same transform the
  parent step uses, so the server-side prompt cache is reused where possible
  (mid-task the prefix ends with synthetic aborted results for tool calls that
  have not returned yet; the cached prefix up to that point still hits).
- system prompt / tools / model / thinking come from the parent profile, so the
  cache key matches. Tools stay attached (``tools=[]`` would bust the cache) and
  the appended instruction is what keeps the model from calling them; nothing
  here would execute a tool call anyway.
- Nothing is appended to ``session.conversation_history`` by this module. The
  caller persists the answer as a ``SideQuestionEntry`` sidecar, which LLM-input
  paths filter out.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.cache_safe import CacheSafeParams, build_cache_safe_messages
from klaude_code.log import DebugType, log_debug
from klaude_code.prompts.side_question import SIDE_QUESTION_PROMPT
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session


class SideQuestionError(RuntimeError):
    """The side question produced no usable answer."""


@dataclass(frozen=True)
class SideQuestionResult:
    answer: str
    usage: Usage | None
    cache_hit_rate: float | None = None
    """Share of this request's prompt that was read from the parent's cache."""


async def run_side_question(
    *,
    session: Session,
    main_profile: AgentProfile,
    question: str,
) -> SideQuestionResult:
    """Ask the main model a side question in one turn.

    Raises :class:`SideQuestionError` when the stream fails or returns no text
    (for example when the model answered with a tool call instead).
    """
    prefix = session.get_llm_history()
    extra: list[message.HistoryEvent] = [
        message.UserMessage(parts=[message.TextPart(text=SIDE_QUESTION_PROMPT.format(question=question))])
    ]
    cache_safe = CacheSafeParams(
        profile=main_profile,
        prefix_messages=prefix,
        prompt_cache_key=session.prompt_cache_key,
    )
    wire = build_cache_safe_messages(cache_safe, extra)

    call_param = llm_param.LLMCallParameter(
        input=[m for m in wire if isinstance(m, message.Message)],
        system=main_profile.system_prompt,
        session_id=session.id,
        prompt_cache_key=cache_safe.prompt_cache_key,
    )
    # Must match the parent request: tools=[] or a max_tokens clamp would change
    # the cache key (see agent/cache_safe.py).
    call_param.tools = main_profile.tools

    try:
        stream = await main_profile.llm_client.call(call_param)
    except Exception as exc:
        raise SideQuestionError(str(exc)) from exc

    accumulated: list[str] = []
    final_message: message.AssistantMessage | None = None
    try:
        async for item in stream:
            if isinstance(item, message.AssistantTextDelta):
                accumulated.append(item.content)
            elif isinstance(item, message.StreamErrorItem):
                raise SideQuestionError(item.error)
            elif isinstance(item, message.AssistantMessage):
                final_message = item
    except asyncio.CancelledError:
        raise
    except SideQuestionError:
        raise
    except Exception as exc:
        raise SideQuestionError(str(exc)) from exc

    answer = (message.join_text_parts(final_message.parts) if final_message else "".join(accumulated)).strip()
    usage = final_message.usage if final_message else None
    hit_rate: float | None = None
    if usage is not None:
        # Providers disagree on whether input_tokens includes cached/write tokens;
        # normalize to the true prompt total the same way fork cache stats do.
        total = max(usage.input_tokens, usage.cached_tokens + usage.cache_write_tokens)
        hit_rate = (usage.cached_tokens / total) if total > 0 else 0.0
        log_debug(
            f"[SideQuestion] usage cache_hit={hit_rate:.2%} read={usage.cached_tokens} "
            f"write={usage.cache_write_tokens} input={usage.input_tokens} output={usage.output_tokens}",
            debug_type=DebugType.RESPONSE,
        )
    if not answer:
        raise SideQuestionError("the model returned no answer text")
    return SideQuestionResult(answer=answer, usage=usage, cache_hit_rate=hit_rate)
