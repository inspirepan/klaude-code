import type { MessageItem } from "../types/message";
import {
  parseCompactionSummary,
  parseDeveloperUIItems,
  parseSubAgents,
  parseTaskMetadataAgent,
  parseUserMessageImages,
} from "./event-parsers";
import { reduceStatusEvent, type SessionStatusState } from "./status-reducer";

export type { SessionStatusState };

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
  statusBySessionId: Partial<Record<string, SessionStatusState>>;
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
  "session.holder.acquired",
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
      if (item.type !== "assistant_text") continue;
      if (item.sessionId === sessionId && item.responseId === responseId) {
        return i;
      }
    }
  }

  const activeItem = state.items[state.activeTextIndex] as MessageItem | undefined;
  if (
    activeItem !== undefined &&
    activeItem.type === "assistant_text" &&
    activeItem.sessionId === sessionId
  ) {
    return state.activeTextIndex;
  }

  return -1;
}

function stopStreamingItems(state: ReducerState): ReducerState {
  const hasStreaming = state.items.some((item) => "isStreaming" in item && item.isStreaming);
  if (!hasStreaming && state.activeTextIndex === -1 && state.activeThinkingIndex === -1) {
    return state;
  }
  const nextItems = hasStreaming
    ? state.items.map((item) => {
        if ("isStreaming" in item && item.isStreaming) {
          return { ...item, isStreaming: false };
        }
        return item;
      })
    : state.items;
  return {
    ...state,
    items: nextItems,
    activeTextIndex: -1,
    activeThinkingIndex: -1,
  };
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

      if (sessionId !== null && currentState.subAgentFinishedBySessionId[sessionId]) {
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
      if (currentState.subAgentFinishedBySessionId[sourceSessionId]) return currentState;
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

      const mainAgentRec = mainAgent as Record<string, unknown>;
      const isPartial = event.is_partial === true;

      const id = makeId(currentState);
      return {
        ...currentState,
        items: [
          ...currentState.items,
          {
            id,
            type: "task_metadata",
            timestamp: ts,
            sessionId: sourceSessionId,
            mainAgent: parseTaskMetadataAgent(mainAgentRec),
            subAgents: parseSubAgents(
              (metadata as Record<string, unknown>).sub_agent_task_metadata,
            ),
            isPartial,
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
