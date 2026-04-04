"""Prompt-prefix cache tracking: hit rate computation and break detection.

Consolidates all cache-related turn-over-turn tracking:
- Cache hit rate: ``cached_tokens[N] / input_tokens[N-1]``, fed to the spinner.
- Cache break detection: alerts when cached tokens drop significantly between
  turns, writes a report file with diagnosis.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from klaude_code.const import DEFAULT_DEBUG_LOG_DIR
from klaude_code.protocol import llm_param, model

_REPORT_DIR = DEFAULT_DEBUG_LOG_DIR / "cache-break-reports"

# --- Break detection thresholds ---
_MIN_TOKEN_DROP = 2_000  # Minimum absolute drop to flag
_DROP_RATIO = 0.05  # Minimum relative drop (5%)
_TTL_5MIN_S = 5 * 60
_TTL_1HOUR_S = 60 * 60


def _hash(data: object) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class _Snapshot:
    system_hash: str
    tools_hash: str
    model_name: str
    system_chars: int
    tool_names: list[str]


@dataclass
class CacheBreakReport:
    reason: str
    call_number: int
    prev_cached_tokens: int
    curr_cached_tokens: int
    token_drop: int
    time_gap_s: float | None
    prev_snapshot: _Snapshot
    curr_snapshot: _Snapshot

    @property
    def summary(self) -> str:
        return (
            f"Prompt cache break detected: {self.reason} "
            f"(cached tokens: {self.prev_cached_tokens:,} -> {self.curr_cached_tokens:,}, "
            f"drop: {self.token_drop:,})"
        )

    def write_report(self) -> str:
        """Write a detailed report file and return its path as a string."""
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = uuid.uuid4().hex[:8]
        path = _REPORT_DIR / f"cache-break-{ts}-{uid}.txt"

        lines = [
            "Prompt Cache Break Report",
            "========================",
            f"Time: {datetime.now().isoformat()}",
            f"Turn: #{self.call_number}",
            "",
            "## Summary",
            f"Reason: {self.reason}",
            f"Cached tokens: {self.prev_cached_tokens:,} -> {self.curr_cached_tokens:,} (drop: {self.token_drop:,})",
            f"Time since last call: {self.time_gap_s:.1f}s" if self.time_gap_s else "Time since last call: N/A",
            "",
            "## Previous State",
            f"Model: {self.prev_snapshot.model_name}",
            f"System prompt hash: {self.prev_snapshot.system_hash}",
            f"System prompt length: {self.prev_snapshot.system_chars:,} chars",
            f"Tools hash: {self.prev_snapshot.tools_hash}",
            f"Tools ({len(self.prev_snapshot.tool_names)}): {', '.join(self.prev_snapshot.tool_names)}",
            "",
            "## Current State",
            f"Model: {self.curr_snapshot.model_name}",
            f"System prompt hash: {self.curr_snapshot.system_hash}",
            f"System prompt length: {self.curr_snapshot.system_chars:,} chars",
            f"Tools hash: {self.curr_snapshot.tools_hash}",
            f"Tools ({len(self.curr_snapshot.tool_names)}): {', '.join(self.curr_snapshot.tool_names)}",
            "",
            "## Diff",
        ]

        if self.prev_snapshot.system_hash != self.curr_snapshot.system_hash:
            lines.append("System prompt content changed (hashes differ)")
        else:
            lines.append("System prompt content unchanged")

        if self.prev_snapshot.tools_hash != self.curr_snapshot.tools_hash:
            prev_set = set(self.prev_snapshot.tool_names)
            curr_set = set(self.curr_snapshot.tool_names)
            added = sorted(curr_set - prev_set)
            removed = sorted(prev_set - curr_set)
            if added:
                lines.append(f"Tools added: {', '.join(added)}")
            if removed:
                lines.append(f"Tools removed: {', '.join(removed)}")
            if not added and not removed:
                lines.append("Tool set unchanged but schema/description changed")
        else:
            lines.append("Tools unchanged")

        path.write_text("\n".join(lines) + "\n")
        return str(path)


class CacheTracker:
    """Tracks prompt-prefix cache across turns.

    Owned by ``MetadataAccumulator``; handles both the per-turn hit rate
    (for the spinner) and cache-break detection (for the error alert).
    """

    def __init__(self) -> None:
        # --- hit rate state ---
        self._prev_turn_input_tokens: int = 0
        self._hit_rate_sum: float = 0.0
        self._hit_rate_count: int = 0
        self.last_hit_rate: float | None = None
        self.last_cached_tokens: int = 0
        self.last_prev_input_tokens: int = 0

        # --- break detection state ---
        self._prev_snapshot: _Snapshot | None = None
        self._prev_cached_tokens: int | None = None
        self._prev_call_time: float | None = None
        self._call_count: int = 0
        self._pending_snapshot: _Snapshot | None = None

    # -- public: called by MetadataAccumulator ---------------------

    @property
    def prev_turn_input_tokens(self) -> int:
        """Input token count from the most recent successful turn (for first-token timeout)."""
        return self._prev_turn_input_tokens

    @property
    def avg_hit_rate(self) -> float | None:
        """Average cache hit rate across all turns (for task metadata)."""
        return self._hit_rate_sum / self._hit_rate_count if self._hit_rate_count > 0 else None

    def record_pre_call_state(
        self,
        system_prompt: str | None,
        tools: list[llm_param.ToolSchema],
        model_name: str,
    ) -> None:
        """Snapshot prompt/tool state before each LLM call (phase 1 of break detection)."""
        system_str = system_prompt or ""
        tool_dicts = [t.model_dump(exclude_none=True) for t in tools]
        self._pending_snapshot = _Snapshot(
            system_hash=_hash(system_str),
            tools_hash=_hash(tool_dicts),
            model_name=model_name,
            system_chars=len(system_str),
            tool_names=[t.name for t in tools],
        )
        self._call_count += 1

    def update(self, usage: model.Usage) -> CacheBreakReport | None:
        """Process a turn's usage: compute hit rate and check for cache break.

        Returns a ``CacheBreakReport`` if a break is detected, ``None`` otherwise.
        """
        # --- hit rate ---
        if self._prev_turn_input_tokens > 0:
            hit_rate = usage.cached_tokens / self._prev_turn_input_tokens
            self._hit_rate_sum += hit_rate
            self._hit_rate_count += 1
            self.last_hit_rate = hit_rate
            self.last_cached_tokens = usage.cached_tokens
            self.last_prev_input_tokens = self._prev_turn_input_tokens
        else:
            self.last_hit_rate = None
            self.last_cached_tokens = 0
            self.last_prev_input_tokens = 0

        # Use the larger value as denominator baseline so cache hit rate remains
        # stable across providers with different usage field semantics.
        self._prev_turn_input_tokens = max(
            usage.input_tokens,
            usage.cached_tokens + usage.cache_write_tokens,
        )

        return self._check_break(usage.cached_tokens)

    def notify_compaction(self) -> None:
        """Reset break-detection baseline after compaction (expected cache drop)."""
        self._prev_cached_tokens = None

    # -- private ---------------------------------------------------

    def _check_break(self, cached_tokens: int) -> CacheBreakReport | None:
        snapshot = self._pending_snapshot
        if snapshot is None:
            return None

        now = time.monotonic()
        prev_cached = self._prev_cached_tokens
        prev_snapshot = self._prev_snapshot
        prev_time = self._prev_call_time

        # Update baseline
        self._prev_cached_tokens = cached_tokens
        self._prev_snapshot = snapshot
        self._prev_call_time = now
        self._pending_snapshot = None

        # First call: no baseline
        if prev_cached is None or prev_snapshot is None:
            return None

        token_drop = prev_cached - cached_tokens
        if token_drop < _MIN_TOKEN_DROP:
            return None
        if cached_tokens >= prev_cached * (1 - _DROP_RATIO):
            return None

        # Diagnose cause
        changes: list[str] = []
        if snapshot.model_name != prev_snapshot.model_name:
            changes.append(f"model changed ({prev_snapshot.model_name} -> {snapshot.model_name})")
        if snapshot.system_hash != prev_snapshot.system_hash:
            delta = snapshot.system_chars - prev_snapshot.system_chars
            sign = "+" if delta >= 0 else ""
            changes.append(f"system prompt changed ({sign}{delta} chars)")
        if snapshot.tools_hash != prev_snapshot.tools_hash:
            prev_set = set(prev_snapshot.tool_names)
            curr_set = set(snapshot.tool_names)
            added = curr_set - prev_set
            removed = prev_set - curr_set
            if added or removed:
                changes.append(f"tools changed (+{len(added)}/-{len(removed)})")
            else:
                changes.append("tool schema changed (same tool set)")

        time_gap = (now - prev_time) if prev_time is not None else None
        if not changes and time_gap is not None:
            if time_gap > _TTL_1HOUR_S:
                changes.append("possible 1h TTL expiry (prompt unchanged)")
            elif time_gap > _TTL_5MIN_S:
                changes.append("possible 5min TTL expiry (prompt unchanged)")
            else:
                changes.append("likely server-side (prompt unchanged, <5min gap)")

        reason = ", ".join(changes) if changes else "unknown cause"
        return CacheBreakReport(
            reason=reason,
            call_number=self._call_count,
            prev_cached_tokens=prev_cached,
            curr_cached_tokens=cached_tokens,
            token_drop=token_drop,
            time_gap_s=time_gap,
            prev_snapshot=prev_snapshot,
            curr_snapshot=snapshot,
        )
