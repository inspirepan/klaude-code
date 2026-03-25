import type { SessionRuntimeState, SessionGroup, SessionSummary } from "@/types/session";
import {
  parsePendingUserInteractionRequest,
  type PendingUserInteractionRequest,
} from "@/types/interaction";

export const defaultRuntimeState: SessionRuntimeState = {
  sessionState: "idle",
  wsState: "idle",
  lastError: null,
};

export function updateRuntimeState(
  current: Partial<Record<string, SessionRuntimeState>>,
  sessionId: string,
  patch: Partial<SessionRuntimeState>,
): Partial<Record<string, SessionRuntimeState>> {
  const previous = current[sessionId] ?? defaultRuntimeState;
  const next = {
    ...previous,
    ...patch,
  };
  if (
    previous.sessionState === next.sessionState &&
    previous.wsState === next.wsState &&
    previous.lastError === next.lastError
  ) {
    return current;
  }
  return {
    ...current,
    [sessionId]: next,
  };
}

export function deleteSessionFromGroups(groups: SessionGroup[], sessionId: string): SessionGroup[] {
  return groups
    .map((group) => ({
      ...group,
      sessions: group.sessions.filter((session) => session.id !== sessionId),
    }))
    .filter((group) => group.sessions.length > 0);
}

export function upsertSessionIntoGroups(
  groups: SessionGroup[],
  session: SessionSummary,
): SessionGroup[] {
  const nextGroups = groups.map((group) => ({
    work_dir: group.work_dir,
    sessions: [...group.sessions],
  }));

  const targetGroupIndex = nextGroups.findIndex((group) => group.work_dir === session.work_dir);
  if (targetGroupIndex === -1) {
    return [{ work_dir: session.work_dir, sessions: [session] }, ...nextGroups];
  }

  const targetGroup = nextGroups[targetGroupIndex];
  const sessionIndex = targetGroup.sessions.findIndex((item) => item.id === session.id);
  if (sessionIndex >= 0) {
    targetGroup.sessions[sessionIndex] = session;
  } else {
    targetGroup.sessions.unshift(session);
  }
  targetGroup.sessions.sort((a, b) => b.updated_at - a.updated_at);
  return nextGroups;
}

export function mergeCollapseState(
  groups: SessionGroup[],
  collapsedByWorkDir: Record<string, boolean>,
): Record<string, boolean> {
  const next: Record<string, boolean> = { ...collapsedByWorkDir };
  for (const group of groups) {
    if (!(group.work_dir in next)) {
      next[group.work_dir] = false;
    }
  }
  return next;
}

export function findSession(groups: SessionGroup[], sessionId: string): SessionSummary | null {
  for (const group of groups) {
    const session = group.sessions.find((item) => item.id === sessionId);
    if (session !== undefined) {
      return session;
    }
  }
  return null;
}

export function patchRuntimeByEvent(
  current: Partial<Record<string, SessionRuntimeState>>,
  sessionId: string,
  eventType: string,
): Partial<Record<string, SessionRuntimeState>> {
  if (eventType === "task.start") {
    return updateRuntimeState(current, sessionId, { sessionState: "running" });
  }
  if (eventType === "task.finish") {
    return updateRuntimeState(current, sessionId, { sessionState: "idle" });
  }
  if (eventType === "user.interaction.request") {
    return updateRuntimeState(current, sessionId, { sessionState: "waiting_user_input" });
  }
  if (eventType === "user.interaction.resolved" || eventType === "user.interaction.cancelled") {
    return updateRuntimeState(current, sessionId, { sessionState: "running" });
  }
  return current;
}

function upsertPendingInteraction(
  current: PendingUserInteractionRequest[],
  request: PendingUserInteractionRequest,
): PendingUserInteractionRequest[] {
  const existingIndex = current.findIndex((item) => item.requestId === request.requestId);
  if (existingIndex === -1) {
    return [...current, request];
  }
  const previous = current[existingIndex];
  if (
    previous.payload === request.payload &&
    previous.source === request.source &&
    previous.toolCallId === request.toolCallId
  ) {
    return current;
  }
  const next = [...current];
  next[existingIndex] = request;
  return next;
}

function removePendingInteraction(
  current: PendingUserInteractionRequest[],
  requestId: string,
): PendingUserInteractionRequest[] {
  const next = current.filter((item) => item.requestId !== requestId);
  return next.length === current.length ? current : next;
}

export function patchPendingInteractionsByEvent(
  current: Record<string, PendingUserInteractionRequest[]>,
  sessionId: string,
  eventType: string,
  event: Record<string, unknown>,
): Record<string, PendingUserInteractionRequest[]> {
  const existing = current[sessionId] ?? [];

  if (eventType === "user.interaction.request") {
    const parsed = parsePendingUserInteractionRequest(event);
    if (parsed === null) {
      return current;
    }
    const nextSessionItems = upsertPendingInteraction(existing, parsed);
    if (nextSessionItems === existing) {
      return current;
    }
    return {
      ...current,
      [sessionId]: nextSessionItems,
    };
  }

  if (eventType === "user.interaction.resolved" || eventType === "user.interaction.cancelled") {
    const requestId = typeof event.request_id === "string" ? event.request_id : null;
    if (requestId === null) {
      return current;
    }
    const nextSessionItems = removePendingInteraction(existing, requestId);
    if (nextSessionItems === existing) {
      return current;
    }
    return {
      ...current,
      [sessionId]: nextSessionItems,
    };
  }

  return current;
}

export function pushSessionUrl(sessionId: string): void {
  if (sessionId === "draft") {
    if (window.location.pathname !== "/") {
      history.pushState(null, "", "/");
    }
    return;
  }
  const prefix = `/session/${sessionId}`;
  // Don't push if already on this session (including sub-agent paths like /session/{id}/agent/{subId})
  if (!window.location.pathname.startsWith(prefix)) {
    history.pushState(null, "", prefix);
  }
}

export function loadCollapsedByWorkDir(): Record<string, boolean> {
  const raw = window.localStorage.getItem(SESSION_GROUP_COLLAPSE_STORAGE_KEY);
  if (raw === null) return {};

  try {
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return {};

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

export function persistCollapsedByWorkDir(collapsedByWorkDir: Record<string, boolean>): void {
  window.localStorage.setItem(
    SESSION_GROUP_COLLAPSE_STORAGE_KEY,
    JSON.stringify(collapsedByWorkDir),
  );
}

const SESSION_GROUP_COLLAPSE_STORAGE_KEY = "klaude:left-sidebar:collapsed-groups";
