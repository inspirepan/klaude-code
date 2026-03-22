import type { ReducerState } from "./event-reducer";
import { DEFAULT_MAX_TOKENS, parseFiniteNumber } from "./event-parsers";

export interface SessionStatusState {
  sessionId: string;
  isSubAgent: boolean;
  subAgentType: string | null;
  subAgentDesc: string | null;
  taskActive: boolean;
  awaitingInput: boolean;
  thinkingActive: boolean;
  compacting: boolean;
  isComposing: boolean;
  assistantCharCount: number;
  tokenInput: number | null;
  tokenCached: number | null;
  tokenCacheWrite: number | null;
  tokenOutput: number | null;
  tokenThought: number | null;
  cacheHitRate: number | null;
  contextSize: number | null;
  contextEffectiveLimit: number | null;
  contextPercent: number | null;
  totalCost: number | null;
  currency: string;
  taskStartedAt: number | null;
  taskElapsedSeconds: number | null;
}

export function createInitialSessionStatus(sessionId: string): SessionStatusState {
  return {
    sessionId,
    isSubAgent: false,
    subAgentType: null,
    subAgentDesc: null,
    taskActive: false,
    awaitingInput: false,
    thinkingActive: false,
    compacting: false,
    isComposing: false,
    assistantCharCount: 0,
    tokenInput: null,
    tokenCached: null,
    tokenCacheWrite: null,
    tokenOutput: null,
    tokenThought: null,
    cacheHitRate: null,
    contextSize: null,
    contextEffectiveLimit: null,
    contextPercent: null,
    totalCost: null,
    currency: "USD",
    taskStartedAt: null,
    taskElapsedSeconds: null,
  };
}

export function getSessionStatus(state: ReducerState, sessionId: string): SessionStatusState {
  return state.statusBySessionId[sessionId] ?? createInitialSessionStatus(sessionId);
}

export function updateSessionStatus(
  state: ReducerState,
  sessionId: string,
  updater: (current: SessionStatusState) => SessionStatusState,
): ReducerState {
  const current = getSessionStatus(state, sessionId);
  const next = updater(current);
  if (next === current) return state;
  return {
    ...state,
    statusBySessionId: {
      ...state.statusBySessionId,
      [sessionId]: next,
    },
  };
}

function clearTaskScopedStatus(
  status: SessionStatusState,
  finishedAt: number | null = null,
): SessionStatusState {
  const elapsed =
    status.taskStartedAt != null && finishedAt != null
      ? Math.max(0, Math.floor(finishedAt - status.taskStartedAt))
      : status.taskElapsedSeconds;
  return {
    ...status,
    taskActive: false,
    awaitingInput: false,
    thinkingActive: false,
    compacting: false,
    isComposing: false,
    assistantCharCount: 0,
    taskStartedAt: null,
    taskElapsedSeconds: elapsed,
  };
}

function resolveSessionId(event: Record<string, unknown>): string | null {
  return typeof event.session_id === "string" ? event.session_id : null;
}

export function reduceStatusEvent(
  state: ReducerState,
  eventType: string,
  event: Record<string, unknown>,
  timestamp: number | null,
): ReducerState {
  const sessionId = resolveSessionId(event);

  switch (eventType) {
    case "task.start": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => {
        const subAgentState =
          event.sub_agent_state !== null && typeof event.sub_agent_state === "object"
            ? (event.sub_agent_state as Record<string, unknown>)
            : null;
        return {
          ...current,
          isSubAgent: subAgentState !== null,
          subAgentType:
            subAgentState !== null && typeof subAgentState.sub_agent_type === "string"
              ? subAgentState.sub_agent_type
              : null,
          subAgentDesc:
            subAgentState !== null && typeof subAgentState.sub_agent_desc === "string"
              ? subAgentState.sub_agent_desc
              : null,
          taskActive: true,
          awaitingInput: false,
          thinkingActive: false,
          compacting: false,
          isComposing: false,
          assistantCharCount: 0,
          taskStartedAt: timestamp,
        };
      });
    }

    case "task.finish": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) =>
        clearTaskScopedStatus(current, timestamp),
      );
    }

    case "interrupt": {
      if (sessionId === null) return state;
      const nextState = updateSessionStatus(state, sessionId, (current) =>
        clearTaskScopedStatus(current, timestamp),
      );
      const interruptedSession = getSessionStatus(nextState, sessionId);
      if (interruptedSession.isSubAgent) {
        return nextState;
      }
      let changed = false;
      const nextStatuses: Record<string, SessionStatusState> = { ...nextState.statusBySessionId };
      for (const [childSessionId, status] of Object.entries(nextState.statusBySessionId)) {
        if (!status.isSubAgent || !status.taskActive) continue;
        nextStatuses[childSessionId] = clearTaskScopedStatus(status, timestamp);
        changed = true;
      }
      if (!changed) return nextState;
      return {
        ...nextState,
        statusBySessionId: nextStatuses,
      };
    }

    case "end": {
      const nowSec = Date.now() / 1000;
      let changed = false;
      const nextStatuses: Record<string, SessionStatusState> = {};
      for (const [existingSessionId, status] of Object.entries(state.statusBySessionId)) {
        if (
          !status.taskActive &&
          !status.awaitingInput &&
          !status.thinkingActive &&
          !status.compacting &&
          !status.isComposing &&
          status.taskStartedAt === null
        ) {
          nextStatuses[existingSessionId] = status;
          continue;
        }
        nextStatuses[existingSessionId] = clearTaskScopedStatus(status, nowSec);
        changed = true;
      }
      if (!changed) return state;
      return {
        ...state,
        statusBySessionId: nextStatuses,
      };
    }

    case "error": {
      if (sessionId === null || event.can_retry === true) return state;
      return updateSessionStatus(state, sessionId, (current) =>
        clearTaskScopedStatus(current, timestamp),
      );
    }

    case "user.interaction.request": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        awaitingInput: true,
      }));
    }

    case "user.interaction.resolved":
    case "user.interaction.cancelled": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        awaitingInput: false,
      }));
    }

    case "compaction.start": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        compacting: true,
      }));
    }

    case "compaction.end": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        compacting: false,
      }));
    }

    case "thinking.start": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        thinkingActive: true,
      }));
    }

    case "thinking.end": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        thinkingActive: false,
      }));
    }

    case "assistant.text.start": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        isComposing: true,
        assistantCharCount: 0,
      }));
    }

    case "assistant.text.delta": {
      if (sessionId === null) return state;
      const deltaLength = typeof event.content === "string" ? event.content.length : 0;
      if (deltaLength === 0) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        assistantCharCount: current.assistantCharCount + deltaLength,
      }));
    }

    case "assistant.text.end":
    case "response.complete": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        isComposing: false,
      }));
    }

    case "tool.call.start": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        isComposing: false,
      }));
    }

    case "tool.call": {
      if (sessionId === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        isComposing: false,
      }));
    }

    case "usage": {
      if (sessionId === null) return state;
      const usage = event.usage;
      if (usage === null || typeof usage !== "object") return state;
      const payload = usage as Record<string, unknown>;

      const inputTokens = parseFiniteNumber(payload.input_tokens) ?? 0;
      const cachedTokens = parseFiniteNumber(payload.cached_tokens) ?? 0;
      const cacheWriteTokens = parseFiniteNumber(payload.cache_write_tokens) ?? 0;
      const outputTokens = parseFiniteNumber(payload.output_tokens) ?? 0;
      const reasoningTokens = parseFiniteNumber(payload.reasoning_tokens) ?? 0;
      const hasTokenUsage =
        inputTokens > 0 ||
        cachedTokens > 0 ||
        cacheWriteTokens > 0 ||
        outputTokens > 0 ||
        reasoningTokens > 0;

      const contextPercent = parseFiniteNumber(payload.context_usage_percent);
      const contextLimit = parseFiniteNumber(payload.context_limit);
      const maxTokens = parseFiniteNumber(payload.max_tokens) ?? DEFAULT_MAX_TOKENS;
      const contextSize = parseFiniteNumber(payload.context_size);
      const totalCost = parseFiniteNumber(payload.total_cost);
      const currency = typeof payload.currency === "string" ? payload.currency : "USD";

      return updateSessionStatus(state, sessionId, (current) => {
        let next = current;
        if (hasTokenUsage) {
          next = {
            ...next,
            tokenInput:
              (next.tokenInput ?? 0) + Math.max(inputTokens - cachedTokens - cacheWriteTokens, 0),
            tokenCached: (next.tokenCached ?? 0) + cachedTokens,
            tokenCacheWrite: (next.tokenCacheWrite ?? 0) + cacheWriteTokens,
            tokenOutput: (next.tokenOutput ?? 0) + Math.max(outputTokens - reasoningTokens, 0),
            tokenThought: (next.tokenThought ?? 0) + reasoningTokens,
          };
        }
        if (contextPercent !== null) {
          const effectiveLimit = (contextLimit ?? 0) - maxTokens;
          next = {
            ...next,
            contextSize,
            contextEffectiveLimit: effectiveLimit > 0 ? effectiveLimit : null,
            contextPercent,
          };
        }
        if (totalCost !== null) {
          next = {
            ...next,
            totalCost: (next.totalCost ?? 0) + totalCost,
            currency,
          };
        }
        return next;
      });
    }

    case "cache.hit.rate": {
      if (sessionId === null) return state;
      const cacheHitRate = parseFiniteNumber(event.cache_hit_rate);
      if (cacheHitRate === null) return state;
      return updateSessionStatus(state, sessionId, (current) => ({
        ...current,
        cacheHitRate,
      }));
    }

    default:
      return state;
  }
}
