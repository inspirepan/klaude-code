"""Records the LLM calls the agent makes outside a normal step.

A main-agent step already persists everything a reader needs on
``AssistantMessage.usage``. The three out-of-band calls -- compaction, the
``/btw`` side question and ``/rewind``'s fork summary -- computed the same
numbers and threw them away. This module is the pipe, not new measurement: it
wraps an existing call site and freezes the result into an
``message.LLMRequestEntry`` sidecar.

Ownership rule: the CALLER creates the :class:`LLMRequestLog` and passes it in,
so a call that fails still leaves its record behind for whoever writes history.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import llm_param, message
from klaude_code.session.session import Session

# Not model knobs: the wire payload, the routing identity, and `disabled`
# (a config-availability flag that says nothing about the request). `input` in
# particular is the whole conversation, which the ledger already holds.
_NON_OPTION_FIELDS: set[str] = {"input", "system", "tools", "session_id", "prompt_cache_key", "disabled"}


def safe_call_options(param: llm_param.LLMCallParameter) -> dict[str, Any]:
    """Dump the effective call knobs, minus payload and credentials.

    Read this AFTER the call: provider clients run ``apply_config_defaults``
    on the same object, so by then the ``None`` fields hold the values that
    were actually sent.
    """
    excluded = _NON_OPTION_FIELDS | llm_param.LLM_CONFIG_SECRET_FIELDS
    return param.model_dump(mode="json", exclude_none=True, exclude=excluded)


class LLMRequestRecord:
    """One in-flight call. Freezes into an entry when its block exits."""

    def __init__(
        self,
        *,
        kind: message.LLMRequestKind,
        label: str | None,
        client: LLMClientABC | None,
    ) -> None:
        self._kind = kind
        self._label = label
        self._client = client
        self._param: llm_param.LLMCallParameter | None = None
        self._started_at = datetime.now()
        self._first_token_at: datetime | None = None
        self._completed_at: datetime | None = None
        self._usage: message.Usage | None = None
        self._tool_call_count = 0
        self._stream_tool_calls = 0
        self._status: message.LLMRequestStatus = "completed"
        self._error: str | None = None

    def start(self, param: llm_param.LLMCallParameter) -> None:
        """Mark the provider call as starting now, with these parameters."""
        self._param = param
        self._started_at = datetime.now()

    def observe(self, item: message.LLMStreamItem) -> None:
        """Feed every streamed item through, in order."""
        match item:
            case message.AssistantTextDelta() | message.ThinkingTextDelta():
                self._mark_first_token()
            case message.ToolCallStartDelta():
                self._mark_first_token()
                self._stream_tool_calls += 1
            case message.AssistantMessage() as msg:
                self._usage = msg.usage
                self._tool_call_count = sum(1 for part in msg.parts if isinstance(part, message.ToolCallPart))
            case message.StreamErrorItem() as err:
                self._error = err.error
                self._status = "error"
            case _:
                return

    def _mark_first_token(self) -> None:
        if self._first_token_at is None:
            self._first_token_at = datetime.now()

    def close(self, *, status: message.LLMRequestStatus, error: str | None = None) -> None:
        """Stop the clock and settle the outcome. Idempotent per call site."""
        self._completed_at = datetime.now()
        if status != "completed":
            self._status = status
            if error is not None and self._error is None:
                self._error = error

    def _describe(self) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Provider / model / options of the call. Never raises.

        This runs inside a ``finally`` around a live LLM call: an exception here
        would replace whatever the call itself was raising.
        """
        provider: str | None = None
        model: str | None = None
        options: dict[str, Any] | None = None
        with contextlib.suppress(Exception):
            if self._param is not None:
                options = safe_call_options(self._param)
                model = self._param.model_id or None
            if self._client is not None:
                provider = self._client.get_llm_config().provider_name or None
                if model is None:
                    model = self._client.model_name or None
        return provider, model, options

    def freeze(self) -> message.LLMRequestEntry:
        provider, model, options = self._describe()
        return message.LLMRequestEntry(
            kind=self._kind,
            label=self._label,
            provider=provider,
            model=model,
            options=options,
            status=self._status,
            error=self._error,
            usage=self._usage,
            started_at=self._started_at,
            first_token_at=self._first_token_at,
            completed_at=self._completed_at,
            tool_call_count=self._tool_call_count or self._stream_tool_calls,
        )


class LLMRequestLog:
    """The request entries one operation produced."""

    def __init__(self) -> None:
        self.entries: list[message.LLMRequestEntry] = []

    @property
    def ordered_entries(self) -> list[message.LLMRequestEntry]:
        """Entries in call order. Concurrent calls close out of order, and the
        ledger reads top to bottom, so persist them sorted by start time."""
        return sorted(self.entries, key=lambda entry: entry.started_at)

    @property
    def primary_request_id(self) -> str | None:
        """Id of the first call, which the operation's own entry links to."""
        ordered = self.ordered_entries
        return ordered[0].request_id if ordered else None

    def find(self, label: str) -> message.LLMRequestEntry | None:
        """The first entry with this sub-call label, in call order."""
        return next((entry for entry in self.ordered_entries if entry.label == label), None)

    @contextmanager
    def record(
        self,
        *,
        kind: message.LLMRequestKind,
        label: str | None = None,
        client: LLMClientABC | None = None,
    ) -> Iterator[LLMRequestRecord]:
        """Wrap one provider call; the entry lands in ``entries`` either way."""
        record = LLMRequestRecord(kind=kind, label=label, client=client)
        try:
            yield record
        except asyncio.CancelledError:
            record.close(status="interrupted")
            raise
        except Exception as exc:
            record.close(status="error", error=str(exc) or exc.__class__.__name__)
            raise
        else:
            record.close(status="completed")
        finally:
            self.entries.append(record.freeze())


def append_request_records(session: Session, log: LLMRequestLog) -> None:
    """Persist the records of an operation that produced no entry of its own.

    A failed or interrupted compaction / `/btw` / `/rewind` writes nothing else,
    so without this the call would leave no trace in the ledger at all.
    """
    entries = log.ordered_entries
    if entries:
        session.append_history(list(entries))


__all__ = ["LLMRequestLog", "LLMRequestRecord", "append_request_records", "safe_call_options"]
