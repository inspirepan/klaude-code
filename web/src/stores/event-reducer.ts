import type { DeveloperUIItem, MessageImagePart, MessageItem } from "../types/message";

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
}

export function createInitialState(): ReducerState {
  return {
    items: [],
    nextId: 1,
    activeTextIndex: -1,
    activeThinkingIndex: -1,
    toolBlockByCallId: new Map(),
  };
}

const SKIP_EVENT_TYPES = new Set([
  "task.start",
  "task.finish",
  "task.metadata",
  "turn.start",
  "turn.end",
  "usage",
  "welcome",
  "replay.history",
  "error",
  "compaction.start",
  "compaction.end",
  "rewind",
  "user.interaction.request",
  "user.interaction.resolved",
  "user.interaction.cancelled",
  "operation.accepted",
  "operation.rejected",
  "operation.finished",
  "notice",
  "model.changed",
  "todo.change",
  "cache.hit.rate",
  "usage.snapshot",
  "end",
]);

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
          .filter((o): o is { operation: "Read" | "List"; path: string; mentioned_in: string | null } =>
            o.operation !== null && o.path.length > 0
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

export function reduceEvent(
  state: ReducerState,
  eventType: string,
  event: Record<string, unknown>,
  timestamp: number | null = null,
): ReducerState {
  if (SKIP_EVENT_TYPES.has(eventType)) {
    return state;
  }

  const ts = resolveTimestamp(timestamp, event);

  switch (eventType) {
    case "developer.message": {
      const rawItem = event.item;
      const itemObj = rawItem !== null && typeof rawItem === "object" ? (rawItem as Record<string, unknown>) : null;
      const uiItems = parseDeveloperUIItems(itemObj?.ui_extra);
      if (uiItems.length === 0) return state;
      const id = makeId(state);
      return {
        ...state,
        items: [...state.items, { id, type: "developer_message", timestamp: ts, items: uiItems }],
        nextId: state.nextId + 1,
      };
    }

    case "user.message": {
      const id = makeId(state);
      const content = typeof event.content === "string" ? event.content : "";
      const images = parseUserMessageImages(event.images);
      return {
        ...state,
        items: [...state.items, { id, type: "user_message", timestamp: ts, content, images }],
        nextId: state.nextId + 1,
      };
    }

    case "thinking.start": {
      const id = makeId(state);
      const index = state.items.length;
      return {
        ...state,
        items: [...state.items, { id, type: "thinking", timestamp: ts, content: "", isStreaming: true }],
        nextId: state.nextId + 1,
        activeThinkingIndex: index,
      };
    }

    case "thinking.delta": {
      const idx = state.activeThinkingIndex;
      if (idx < 0 || idx >= state.items.length) return state;
      const item = state.items[idx];
      if (item.type !== "thinking") return state;
      const delta = typeof event.content === "string" ? event.content : "";
      const nextItems = [...state.items];
      nextItems[idx] = { ...item, content: item.content + delta };
      return { ...state, items: nextItems };
    }

    case "thinking.end": {
      const idx = state.activeThinkingIndex;
      if (idx < 0 || idx >= state.items.length) return state;
      const item = state.items[idx];
      if (item.type !== "thinking") return state;
      const nextItems = [...state.items];
      nextItems[idx] = { ...item, isStreaming: false };
      return { ...state, items: nextItems, activeThinkingIndex: -1 };
    }

    case "assistant.text.start": {
      const id = makeId(state);
      const index = state.items.length;
      return {
        ...state,
        items: [...state.items, { id, type: "assistant_text", timestamp: ts, content: "", isStreaming: true }],
        nextId: state.nextId + 1,
        activeTextIndex: index,
      };
    }

    case "assistant.text.delta": {
      const idx = state.activeTextIndex;
      if (idx < 0 || idx >= state.items.length) return state;
      const item = state.items[idx];
      if (item.type !== "assistant_text") return state;
      const delta = typeof event.content === "string" ? event.content : "";
      const nextItems = [...state.items];
      nextItems[idx] = { ...item, content: item.content + delta };
      return { ...state, items: nextItems };
    }

    case "assistant.text.end": {
      const idx = state.activeTextIndex;
      if (idx < 0 || idx >= state.items.length) return state;
      const item = state.items[idx];
      if (item.type !== "assistant_text") return state;
      // For durable events replayed from history, content is on the end event
      const content = typeof event.content === "string" && event.content.length > 0
        ? event.content
        : item.content;
      const nextItems = [...state.items];
      nextItems[idx] = { ...item, content, isStreaming: false };
      return { ...state, items: nextItems, activeTextIndex: -1 };
    }

    case "tool.call.start": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const existingIdx = state.toolBlockByCallId.get(toolCallId);
      if (existingIdx !== undefined) {
        // Already exists (from a previous start), update it
        const item = state.items[existingIdx];
        if (item.type !== "tool_block") return state;
        const nextItems = [...state.items];
        nextItems[existingIdx] = {
          ...item,
          toolName: typeof event.tool_name === "string" ? event.tool_name : item.toolName,
        };
        return { ...state, items: nextItems };
      }
      const id = makeId(state);
      const index = state.items.length;
      const newMap = new Map(state.toolBlockByCallId);
      newMap.set(toolCallId, index);
      return {
        ...state,
        items: [
          ...state.items,
          {
            id,
            type: "tool_block",
            timestamp: ts,
            toolCallId,
            toolName: typeof event.tool_name === "string" ? event.tool_name : "",
            arguments: "",
            result: null,
            resultStatus: null,
            uiExtra: null,
            isStreaming: true,
          },
        ],
        nextId: state.nextId + 1,
        toolBlockByCallId: newMap,
      };
    }

    case "tool.call": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const args = typeof event.arguments === "string" ? event.arguments : "";
      const toolName = typeof event.tool_name === "string" ? event.tool_name : "";

      const existingIdx = state.toolBlockByCallId.get(toolCallId);
      if (existingIdx !== undefined) {
        const item = state.items[existingIdx];
        if (item.type !== "tool_block") return state;
        const nextItems = [...state.items];
        nextItems[existingIdx] = {
          ...item,
          arguments: args || item.arguments,
          toolName: toolName || item.toolName,
        };
        return { ...state, items: nextItems };
      }

      // No existing block, create one
      const id = makeId(state);
      const index = state.items.length;
      const newMap = new Map(state.toolBlockByCallId);
      newMap.set(toolCallId, index);
      return {
        ...state,
        items: [
          ...state.items,
          {
            id,
            type: "tool_block",
            timestamp: ts,
            toolCallId,
            toolName,
            arguments: args,
            result: null,
            resultStatus: null,
            uiExtra: null,
            isStreaming: true,
          },
        ],
        nextId: state.nextId + 1,
        toolBlockByCallId: newMap,
      };
    }

    case "tool.result": {
      const toolCallId = typeof event.tool_call_id === "string" ? event.tool_call_id : "";
      const idx = state.toolBlockByCallId.get(toolCallId);
      if (idx === undefined) return state;
      const item = state.items[idx];
      if (item.type !== "tool_block") return state;

      const result = typeof event.result === "string" ? event.result : null;
      const status = typeof event.status === "string"
        ? (event.status as "success" | "error" | "aborted")
        : null;
      const uiExtra =
        event.ui_extra !== null && typeof event.ui_extra === "object"
          ? (event.ui_extra as Record<string, unknown>)
          : null;

      // For durable replay, tool_name and arguments may also be present
      const toolName = typeof event.tool_name === "string" && event.tool_name.length > 0
        ? event.tool_name
        : item.toolName;
      const args = typeof event.arguments === "string" && event.arguments.length > 0
        ? event.arguments
        : item.arguments;

      const nextItems = [...state.items];
      nextItems[idx] = {
        ...item,
        toolName,
        arguments: args,
        result,
        resultStatus: status,
        uiExtra,
        isStreaming: false,
      };
      return { ...state, items: nextItems };
    }

    case "interrupt": {
      // Stop all streaming
      const nextItems = state.items.map((item) => {
        if ("isStreaming" in item && item.isStreaming) {
          return { ...item, isStreaming: false };
        }
        return item;
      });
      return {
        ...state,
        items: nextItems,
        activeTextIndex: -1,
        activeThinkingIndex: -1,
      };
    }

    default: {
      // Unknown event - show fallback
      const id = makeId(state);
      return {
        ...state,
        items: [
          ...state.items,
          { id, type: "unknown_event", timestamp: ts, eventType, rawEvent: event },
        ],
        nextId: state.nextId + 1,
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
