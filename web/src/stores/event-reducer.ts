import type { DeveloperUIItem, MessageImagePart, MessageItem } from "../types/message";

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
}

function parseUserMessageImages(raw: unknown): MessageImagePart[] {
  if (!Array.isArray(raw)) return [];
  const images: MessageImagePart[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) continue;
    const part = item as Record<string, unknown>;
    if (part.type === "image_url" && typeof part.url === "string") {
      images.push({ type: "image_url", url: part.url });
      continue;
    }
    if (part.type === "image_file" && typeof part.file_path === "string") {
      images.push({ type: "image_file", file_path: part.file_path });
    }
  }
  return images;
}

export interface ReducerState {
  items: MessageItem[];
  nextId: number;
  activeTextIndex: number;
  activeThinkingIndex: number;
  toolBlockByCallId: Map<string, number>;
  subAgentDescBySessionId: Record<string, string>;
  subAgentTypeBySessionId: Record<string, string>;
  subAgentForkBySessionId: Record<string, boolean>;
  subAgentFinishedBySessionId: Record<string, boolean>;
  statusBySessionId: Record<string, SessionStatusState>;
}

function createInitialSessionStatus(sessionId: string): SessionStatusState {
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
  };
}

export function createInitialState(): ReducerState {
  return {
    items: [],
    nextId: 1,
    activeTextIndex: -1,
    activeThinkingIndex: -1,
    toolBlockByCallId: new Map(),
    subAgentDescBySessionId: {},
    subAgentTypeBySessionId: {},
    subAgentForkBySessionId: {},
    subAgentFinishedBySessionId: {},
    statusBySessionId: {},
  };
}

const SKIP_EVENT_TYPES = new Set([
  "turn.start",
  "turn.end",
  "usage",
  "welcome",
  "replay.history",
  "compaction.start",
  "rewind",
  "user.interaction.request",
  "user.interaction.resolved",
  "user.interaction.cancelled",
  "operation.accepted",
  "operation.rejected",
  "operation.finished",
  "notice",
  "model.changed",
  "session.title.changed",
  "todo.change",
  "cache.hit.rate",
  "usage.snapshot",
  "end",
]);

const WORKED_LINE_DURATION_THRESHOLD_S = 60;
const WORKED_LINE_TURN_COUNT_THRESHOLD = 4;
const DEFAULT_MAX_TOKENS = 32000;
function parseFiniteNumber(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

function getSessionStatus(state: ReducerState, sessionId: string): SessionStatusState {
  return state.statusBySessionId[sessionId] ?? createInitialSessionStatus(sessionId);
}

function updateSessionStatus(
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

function clearTaskScopedStatus(status: SessionStatusState): SessionStatusState {
  return {
    ...status,
    taskActive: false,
    awaitingInput: false,
    thinkingActive: false,
    compacting: false,
    isComposing: false,
    assistantCharCount: 0,
    taskStartedAt: null,
  };
}

function stopStreamingItems(state: ReducerState): ReducerState {
  let changed = false;
  const nextItems = state.items.map((item) => {
    if ("isStreaming" in item && item.isStreaming) {
      changed = true;
      return { ...item, isStreaming: false };
    }
    return item;
  });
  if (!changed && state.activeTextIndex === -1 && state.activeThinkingIndex === -1) {
    return state;
  }
  return {
    ...state,
    items: nextItems,
    activeTextIndex: -1,
    activeThinkingIndex: -1,
  };
}

function reduceStatusEvent(
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
      return updateSessionStatus(state, sessionId, (current) => clearTaskScopedStatus(current));
    }

    case "interrupt": {
      if (sessionId === null) return state;
      const nextState = updateSessionStatus(state, sessionId, (current) =>
        clearTaskScopedStatus(current),
      );
      const interruptedSession = getSessionStatus(nextState, sessionId);
      if (interruptedSession.isSubAgent) {
        return nextState;
      }
      let changed = false;
      const nextStatuses: Record<string, SessionStatusState> = { ...nextState.statusBySessionId };
      for (const [childSessionId, status] of Object.entries(nextState.statusBySessionId)) {
        if (!status.isSubAgent || !status.taskActive) continue;
        nextStatuses[childSessionId] = clearTaskScopedStatus(status);
        changed = true;
      }
      if (!changed) return nextState;
      return {
        ...nextState,
        statusBySessionId: nextStatuses,
      };
    }

    case "end": {
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
        nextStatuses[existingSessionId] = clearTaskScopedStatus(status);
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
      return updateSessionStatus(state, sessionId, (current) => clearTaskScopedStatus(current));
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

function parseStringArray(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((v): v is string => typeof v === "string");
}

function parseDeveloperUIItems(raw: unknown): DeveloperUIItem[] {
  if (raw === null || typeof raw !== "object") return [];
  const extra = raw as Record<string, unknown>;
  if (!Array.isArray(extra.items)) return [];

  const out: DeveloperUIItem[] = [];
  for (const item of extra.items) {
    if (item === null || typeof item !== "object") continue;
    const ui = item as Record<string, unknown>;
    const t = ui.type;
    if (typeof t !== "string") continue;

    switch (t) {
      case "memory_loaded": {
        if (!Array.isArray(ui.files)) break;
        const files = ui.files
          .filter((f): f is Record<string, unknown> => f !== null && typeof f === "object")
          .map((f) => ({
            path: typeof f.path === "string" ? f.path : "",
            mentioned_patterns: parseStringArray(f.mentioned_patterns),
          }))
          .filter((f) => f.path.length > 0);
        if (files.length === 0) break;
        out.push({ type: "memory_loaded", files });
        break;
      }
      case "external_file_changes": {
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        if (paths.length === 0) break;
        out.push({ type: "external_file_changes", paths });
        break;
      }
      case "todo_reminder": {
        const reason = ui.reason;
        if (reason !== "empty" && reason !== "not_used_recently") break;
        out.push({ type: "todo_reminder", reason });
        break;
      }
      case "at_file_ops": {
        if (!Array.isArray(ui.ops)) break;
        const ops = ui.ops
          .filter((o): o is Record<string, unknown> => o !== null && typeof o === "object")
          .map((o) => ({
            operation: o.operation === "Read" || o.operation === "List" ? o.operation : null,
            path: typeof o.path === "string" ? o.path : "",
            mentioned_in: typeof o.mentioned_in === "string" ? o.mentioned_in : null,
          }))
          .filter(
            (o): o is { operation: "Read" | "List"; path: string; mentioned_in: string | null } =>
              o.operation !== null && o.path.length > 0,
          );
        if (ops.length === 0) break;
        out.push({ type: "at_file_ops", ops });
        break;
      }
      case "user_images": {
        const count = typeof ui.count === "number" ? ui.count : 0;
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        out.push({ type: "user_images", count, paths });
        break;
      }
      case "skill_activated": {
        const name = typeof ui.name === "string" ? ui.name : "";
        if (name.length === 0) break;
        out.push({ type: "skill_activated", name });
        break;
      }
      case "at_file_images": {
        const paths = parseStringArray(ui.paths).filter((p) => p.length > 0);
        if (paths.length === 0) break;
        out.push({ type: "at_file_images", paths });
        break;
      }
      default:
        break;
    }
  }

  return out;
}

function makeId(state: ReducerState): string {
  return `msg-${state.nextId}`;
}

function resolveTimestamp(explicit: number | null, event: Record<string, unknown>): number | null {
  if (explicit !== null) return explicit;
  if (typeof event.timestamp === "number") return event.timestamp;
  return null;
}

function resolveSessionId(event: Record<string, unknown>): string | null {
  return typeof event.session_id === "string" ? event.session_id : null;
}

function resolveResponseId(event: Record<string, unknown>): string | null {
  return typeof event.response_id === "string" ? event.response_id : null;
}

function findAssistantTextIndex(
  state: ReducerState,
  params: { sessionId: string | null; responseId: string | null },
): number {
  const { sessionId, responseId } = params;
  if (responseId !== null) {
    for (let i = state.items.length - 1; i >= 0; i -= 1) {
      const item = state.items[i];
      if (item?.type !== "assistant_text") continue;
      if (item.sessionId === sessionId && item.responseId === responseId) {
        return i;
      }
    }
  }

  const activeItem = state.items[state.activeTextIndex];
  if (
    activeItem !== undefined &&
    activeItem.type === "assistant_text" &&
    activeItem.sessionId === sessionId
  ) {
    return state.activeTextIndex;
  }

  return -1;
}

function parseCompactionSummary(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const text = raw.trim();
  if (text.length === 0) return null;
  const match = text.match(/<summary>([\s\S]*?)<\/summary>/);
  if (!match) return text;
  const inner = match[1]?.trim() ?? "";
  return inner.length > 0 ? inner : text;
}

export function reduceEvent(
  state: ReducerState,
  eventType: string,
  event: Record<string, unknown>,
  timestamp: number | null = null,
): ReducerState {
  const stateWithStatus = reduceStatusEvent(state, eventType, event, timestamp);

  if (SKIP_EVENT_TYPES.has(eventType)) {
    return stateWithStatus;
  }

  const ts = resolveTimestamp(timestamp, event);
  const sourceSessionId = resolveSessionId(event);
  const responseId = resolveResponseId(event);
  const currentState = stateWithStatus;

  switch (eventType) {
    case "compaction.end": {
      const summary = parseCompactionSummary(event.summary);
      if (summary === null) return currentState;
      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "compaction_summary",
            timestamp: ts,
            sessionId: sourceSessionId,
            content: summary,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "task.start": {
      const sessionId = sourceSessionId;
      let changed = false;
      let nextDescBySessionId = currentState.subAgentDescBySessionId;
      let nextTypeBySessionId = currentState.subAgentTypeBySessionId;
      let nextForkBySessionId = currentState.subAgentForkBySessionId;
      let nextFinishedBySessionId = currentState.subAgentFinishedBySessionId;

      if (sessionId !== null && currentState.subAgentFinishedBySessionId[sessionId] !== false) {
        nextFinishedBySessionId = {
          ...currentState.subAgentFinishedBySessionId,
          [sessionId]: false,
        };
        changed = true;
      }

      const subAgentState = event.sub_agent_state;
      if (sessionId !== null && subAgentState !== null && typeof subAgentState === "object") {
        const subAgentType = (subAgentState as Record<string, unknown>).sub_agent_type;
        if (
          typeof subAgentType === "string" &&
          subAgentType.length > 0 &&
          currentState.subAgentTypeBySessionId[sessionId] !== subAgentType
        ) {
          nextTypeBySessionId = {
            ...currentState.subAgentTypeBySessionId,
            [sessionId]: subAgentType,
          };
          changed = true;
        }

        const desc = (subAgentState as Record<string, unknown>).sub_agent_desc;
        if (
          typeof desc === "string" &&
          desc.length > 0 &&
          currentState.subAgentDescBySessionId[sessionId] !== desc
        ) {
          nextDescBySessionId = {
            ...currentState.subAgentDescBySessionId,
            [sessionId]: desc,
          };
          changed = true;
        }

        const forkContext = (subAgentState as Record<string, unknown>).fork_context;
        if (
          typeof forkContext === "boolean" &&
          currentState.subAgentForkBySessionId[sessionId] !== forkContext
        ) {
          nextForkBySessionId = {
            ...currentState.subAgentForkBySessionId,
            [sessionId]: forkContext,
          };
          changed = true;
        }
      }

      if (!changed) return currentState;
      return {
        ...currentState,
        subAgentDescBySessionId: nextDescBySessionId,
        subAgentTypeBySessionId: nextTypeBySessionId,
        subAgentForkBySessionId: nextForkBySessionId,
        subAgentFinishedBySessionId: nextFinishedBySessionId,
      };
    }

    case "task.finish": {
      if (sourceSessionId === null) return currentState;
      if (currentState.subAgentFinishedBySessionId[sourceSessionId] === true) return currentState;
      return {
        ...currentState,
        subAgentFinishedBySessionId: {
          ...currentState.subAgentFinishedBySessionId,
          [sourceSessionId]: true,
        },
      };
    }

    case "developer.message": {
      const rawItem = event.item;
      const itemObj =
        rawItem !== null && typeof rawItem === "object"
          ? (rawItem as Record<string, unknown>)
          : null;
      const uiItems = parseDeveloperUIItems(itemObj?.ui_extra);
      if (uiItems.length === 0) return currentState;
      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "developer_message",
            timestamp: ts,
            sessionId: sourceSessionId,
            items: uiItems,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "task.metadata": {
      const metadata = event.metadata;
      if (metadata === null || typeof metadata !== "object") return currentState;

      const mainAgent = (metadata as Record<string, unknown>).main_agent;
      if (mainAgent === null || typeof mainAgent !== "object") return currentState;

      const durationSeconds = parseFiniteNumber(
        (mainAgent as Record<string, unknown>).task_duration_s,
      );
      if (durationSeconds === null) return currentState;

      const turnCountRaw = parseFiniteNumber((mainAgent as Record<string, unknown>).turn_count);
      const turnCount = Math.max(0, Math.floor(turnCountRaw ?? 0));
      const shouldShowWorkedLine =
        durationSeconds > WORKED_LINE_DURATION_THRESHOLD_S ||
        turnCount > WORKED_LINE_TURN_COUNT_THRESHOLD;
      if (!shouldShowWorkedLine) return currentState;

      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "task_worked",
            timestamp: ts,
            sessionId: sourceSessionId,
            durationSeconds: Math.max(0, durationSeconds),
            turnCount,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "user.message": {
      const id = makeId(currentState);
      const content = typeof event.content === "string" ? event.content : "";
      const images = parseUserMessageImages(event.images);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          { id, type: "user_message", timestamp: ts, sessionId: sourceSessionId, content, images },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "thinking.start": {
      const id = makeId(currentState);
      const index = currentState.items.length;
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "thinking",
            timestamp: ts,
            sessionId: sourceSessionId,
            content: "",
            isStreaming: true,
          },
        ],
        nextId: currentState.nextId + 1,
        activeThinkingIndex: index,
      };
    }

    case "thinking.delta": {
      const idx = currentState.activeThinkingIndex;
      if (idx < 0 || idx >= currentState.items.length) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "thinking") return currentState;
      const delta = typeof event.content === "string" ? event.content : "";
      const nextItems = [...currentState.items];
      nextItems[idx] = { ...item, content: item.content + delta };
      return { ...currentState, items: nextItems };
    }

    case "thinking.end": {
      const idx = currentState.activeThinkingIndex;
      if (idx < 0 || idx >= currentState.items.length) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "thinking") return currentState;
      const nextItems = [...currentState.items];
      nextItems[idx] = { ...item, isStreaming: false };
      return { ...currentState, items: nextItems, activeThinkingIndex: -1 };
    }

    case "assistant.text.start": {
      const id = makeId(currentState);
      const index = currentState.items.length;
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "assistant_text",
            timestamp: ts,
            sessionId: sourceSessionId,
            responseId,
            content: "",
            isStreaming: true,
          },
        ],
        nextId: currentState.nextId + 1,
        activeTextIndex: index,
      };
    }

    case "assistant.text.delta": {
      const idx = currentState.activeTextIndex;
      if (idx < 0 || idx >= currentState.items.length) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "assistant_text") return currentState;
      const delta = typeof event.content === "string" ? event.content : "";
      const nextItems = [...currentState.items];
      nextItems[idx] = { ...item, content: item.content + delta };
      return { ...currentState, items: nextItems };
    }

    case "assistant.text.end": {
      const idx = findAssistantTextIndex(currentState, { sessionId: sourceSessionId, responseId });
      if (idx < 0 || idx >= currentState.items.length) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "assistant_text") return currentState;
      // For durable events replayed from history, content is on the end event
      const content =
        typeof event.content === "string" && event.content.length > 0
          ? event.content
          : item.content;
      const nextItems = [...currentState.items];
      nextItems[idx] = { ...item, content, isStreaming: false };
      return {
        ...currentState,
        items: nextItems,
        activeTextIndex: idx === currentState.activeTextIndex ? -1 : currentState.activeTextIndex,
      };
    }

    case "response.complete": {
      const content = typeof event.content === "string" ? event.content : "";
      if (content.length === 0) return currentState;

      const idx = findAssistantTextIndex(currentState, { sessionId: sourceSessionId, responseId });
      if (idx >= 0 && idx < currentState.items.length) {
        const item = currentState.items[idx];
        if (item.type !== "assistant_text") return currentState;
        const nextItems = [...currentState.items];
        nextItems[idx] = { ...item, content, isStreaming: false };
        return {
          ...currentState,
          items: nextItems,
          activeTextIndex: idx === currentState.activeTextIndex ? -1 : currentState.activeTextIndex,
        };
      }

      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "assistant_text",
            timestamp: ts,
            sessionId: sourceSessionId,
            responseId,
            content,
            isStreaming: false,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "tool.call.start": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const existingIdx = currentState.toolBlockByCallId.get(toolCallId);
      if (existingIdx !== undefined) {
        // Already exists (from a previous start), update it
        const item = currentState.items[existingIdx];
        if (item.type !== "tool_block") return currentState;
        const nextItems = [...currentState.items];
        nextItems[existingIdx] = {
          ...item,
          toolName: typeof event.tool_name === "string" ? event.tool_name : item.toolName,
        };
        return { ...currentState, items: nextItems };
      }
      const id = makeId(currentState);
      const index = currentState.items.length;
      const newMap = new Map(currentState.toolBlockByCallId);
      newMap.set(toolCallId, index);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "tool_block",
            timestamp: ts,
            sessionId: sourceSessionId,
            toolCallId,
            toolName: typeof event.tool_name === "string" ? event.tool_name : "",
            arguments: "",
            result: null,
            resultStatus: null,
            uiExtra: null,
            isStreaming: true,
            streamingContent: "",
          },
        ],
        nextId: currentState.nextId + 1,
        toolBlockByCallId: newMap,
      };
    }

    case "tool.call": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const args = typeof event.arguments === "string" ? event.arguments : "";
      const toolName = typeof event.tool_name === "string" ? event.tool_name : "";

      const existingIdx = currentState.toolBlockByCallId.get(toolCallId);
      if (existingIdx !== undefined) {
        const item = currentState.items[existingIdx];
        if (item.type !== "tool_block") return currentState;
        const nextItems = [...currentState.items];
        nextItems[existingIdx] = {
          ...item,
          arguments: args || item.arguments,
          toolName: toolName || item.toolName,
        };
        return { ...currentState, items: nextItems };
      }

      // No existing block, create one
      const id = makeId(currentState);
      const index = currentState.items.length;
      const newMap = new Map(currentState.toolBlockByCallId);
      newMap.set(toolCallId, index);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "tool_block",
            timestamp: ts,
            sessionId: sourceSessionId,
            toolCallId,
            toolName,
            arguments: args,
            result: null,
            resultStatus: null,
            uiExtra: null,
            isStreaming: true,
            streamingContent: "",
          },
        ],
        nextId: currentState.nextId + 1,
        toolBlockByCallId: newMap,
      };
    }

    case "tool.output.delta": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const content = typeof event.content === "string" ? event.content : "";
      if (content.length === 0) return currentState;
      const idx = currentState.toolBlockByCallId.get(toolCallId);
      if (idx === undefined) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "tool_block") return currentState;
      const nextItems = [...currentState.items];
      nextItems[idx] = { ...item, streamingContent: item.streamingContent + content };
      return { ...currentState, items: nextItems };
    }

    case "tool.result": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const idx = currentState.toolBlockByCallId.get(toolCallId);
      if (idx === undefined) return currentState;
      const item = currentState.items[idx];
      if (item.type !== "tool_block") return currentState;

      const result = typeof event.result === "string" ? event.result : null;
      const status =
        typeof event.status === "string" ? (event.status as "success" | "error" | "aborted") : null;
      const uiExtra =
        event.ui_extra !== null && typeof event.ui_extra === "object"
          ? (event.ui_extra as Record<string, unknown>)
          : null;

      // For durable replay, tool_name and arguments may also be present
      const toolName =
        typeof event.tool_name === "string" && event.tool_name.length > 0
          ? event.tool_name
          : item.toolName;
      const args =
        typeof event.arguments === "string" && event.arguments.length > 0
          ? event.arguments
          : item.arguments;

      const nextItems = [...currentState.items];
      nextItems[idx] = {
        ...item,
        toolName,
        arguments: args,
        result,
        resultStatus: status,
        uiExtra,
        isStreaming: false,
        streamingContent: "",
      };
      return { ...currentState, items: nextItems };
    }

    case "interrupt": {
      const nextState = stopStreamingItems(currentState);
      const id = makeId(currentState);
      return {
        ...nextState,
        items: [
          ...nextState.items,
          {
            id,
            type: "interrupt",
            timestamp: ts,
            sessionId: sourceSessionId,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    case "error": {
      const message = typeof event.error_message === "string" ? event.error_message.trim() : "";
      const canRetry = event.can_retry === true;
      if (message.length === 0 || canRetry) {
        return stopStreamingItems(currentState);
      }

      const nextState = stopStreamingItems(currentState);
      const id = makeId(currentState);
      return {
        ...nextState,
        items: [
          ...nextState.items,
          {
            id,
            type: "error",
            timestamp: ts,
            sessionId: sourceSessionId,
            message,
            canRetry,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }

    default: {
      // Unknown event - show fallback
      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "unknown_event",
            timestamp: ts,
            sessionId: sourceSessionId,
            eventType,
            rawEvent: event,
          },
        ],
        nextId: currentState.nextId + 1,
      };
    }
  }
}

export function reduceBatch(
  events: Array<{ event_type: string; event: Record<string, unknown>; timestamp?: number }>,
): ReducerState {
  let state = createInitialState();
  for (const { event_type, event, timestamp } of events) {
    state = reduceEvent(state, event_type, event, timestamp ?? null);
  }
  return state;
}
