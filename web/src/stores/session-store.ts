import { create } from "zustand";

import {
  archiveCleanupSessions as archiveCleanupSessionsRequest,
  archiveSession,
  createSession,
  fetchRunningSessions,
  fetchSessionGroups,
  fetchSessionHistory,
  normalizeSessionSummary,
  unarchiveSession,
  type RunningSessionState,
} from "../api/client";
import {
  connectSessionListWs,
  connectSessionWs,
  type SessionWsConnection,
  type SessionListWsEvent,
  type WsErrorFrame,
  type WsEventEnvelope,
} from "../api/ws";
import {
  parsePendingUserInteractionRequest,
  type PendingUserInteractionRequest,
  type UserInteractionResponse,
} from "../types/interaction";
import type {
  ActiveSessionId,
  SessionGroup,
  SessionRuntimeState,
  SessionSummary,
} from "../types/session";
import type { MessageImagePart } from "../types/message";
import { useMessageStore, type MessageStoreEvent } from "./message-store";

interface SessionStoreState {
  groups: SessionGroup[];
  activeSessionId: ActiveSessionId;
  draftWorkDir: string;
  loading: boolean;
  loadError: string | null;
  collapsedByWorkDir: Record<string, boolean>;
  runtimeBySessionId: Record<string, SessionRuntimeState>;
  recentCompletionStartedAtBySessionId: Record<string, number>;
  completedUnreadBySessionId: Record<string, boolean>;
  pendingInteractionsBySessionId: Record<string, PendingUserInteractionRequest[]>;
  initialized: boolean;
  init: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  toggleGroup: (workDir: string) => void;
  setSessionArchived: (sessionId: string, archived: boolean) => Promise<void>;
  archiveCleanupSessions: () => Promise<number>;
  selectDraft: (workDir?: string) => void;
  setDraftWorkDir: (workDir: string) => void;
  selectSession: (sessionId: string) => Promise<void>;
  refreshSession: (sessionId: string) => Promise<void>;
  createSessionFromDraft: (
    firstMessage: string,
    workDir?: string,
    modelName?: string | null,
    images?: MessageImagePart[],
  ) => Promise<string>;
  requestModel: (sessionId: string, preferred: string, saveAsDefault?: boolean) => Promise<void>;
  sendMessage: (sessionId: string, text: string, images?: MessageImagePart[]) => Promise<void>;
  compactSession: (sessionId: string, focus: string | null) => Promise<void>;
  interruptSession: (sessionId: string) => Promise<void>;
  respondInteraction: (
    sessionId: string,
    requestId: string,
    response: UserInteractionResponse,
  ) => Promise<void>;
}

interface ActiveConnection {
  sessionId: string;
  connection: SessionWsConnection;
}

let activeConnection: ActiveConnection | null = null;
let sessionStream: SessionWsConnection | null = null;
let sessionStreamReconnectTimer: ReturnType<typeof setTimeout> | null = null;
let pendingMessageEvents: MessageStoreEvent[] = [];
let pendingMessageEventsFrame = 0;

const SESSION_GROUP_COLLAPSE_STORAGE_KEY = "klaude:left-sidebar:collapsed-groups";

const defaultRuntimeState: SessionRuntimeState = {
  sessionState: "idle",
  wsState: "idle",
  lastError: null,
};

function loadCollapsedByWorkDir(): Record<string, boolean> {
  if (typeof window === "undefined") {
    return {};
  }

  const raw = window.localStorage.getItem(SESSION_GROUP_COLLAPSE_STORAGE_KEY);
  if (raw === null) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }

    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

function persistCollapsedByWorkDir(collapsedByWorkDir: Record<string, boolean>): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    SESSION_GROUP_COLLAPSE_STORAGE_KEY,
    JSON.stringify(collapsedByWorkDir),
  );
}

function updateRuntimeState(
  current: Record<string, SessionRuntimeState>,
  sessionId: string,
  patch: Partial<SessionRuntimeState>,
): Record<string, SessionRuntimeState> {
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

function flushPendingMessageEvents(): void {
  const queuedEvents = pendingMessageEvents;
  if (queuedEvents.length === 0) {
    return;
  }
  pendingMessageEvents = [];
  useMessageStore.getState().handleEvents(queuedEvents);
}

function queueMessageEvents(events: MessageStoreEvent[]): void {
  pendingMessageEvents.push(...events);
  if (pendingMessageEventsFrame !== 0) {
    return;
  }
  pendingMessageEventsFrame = window.requestAnimationFrame(() => {
    pendingMessageEventsFrame = 0;
    flushPendingMessageEvents();
  });
}

async function pollRuntimeStates(get: () => SessionStoreState, set: SetState): Promise<void> {
  try {
    const states = await fetchRunningSessions();

    set((state) => {
      const nextRuntime = { ...state.runtimeBySessionId };
      const nextRecentCompletionStartedAt = { ...state.recentCompletionStartedAtBySessionId };
      const nextCompletedUnread = { ...state.completedUnreadBySessionId };
      let runtimeChanged = false;
      let recentCompletionChanged = false;
      let completedUnreadChanged = false;
      for (const group of state.groups) {
        for (const session of group.sessions) {
          const running: RunningSessionState | undefined = states[session.id];
          const apiState = (running?.session_state ??
            session.session_state) as SessionRuntimeState["sessionState"];
          const prev = nextRuntime[session.id] ?? {
            ...defaultRuntimeState,
            sessionState: session.session_state,
          };
          if (nextRuntime[session.id] === undefined) {
            nextRuntime[session.id] = prev;
            runtimeChanged = true;
          }
          const wsActive = prev.wsState === "connected" || prev.wsState === "connecting";
          const shouldBackfillRunning = prev.sessionState === "idle" && apiState !== "idle";
          const shouldClearStaleRunning = prev.sessionState === "running" && apiState === "idle";
          if (!wsActive || shouldBackfillRunning || shouldClearStaleRunning) {
            if (prev.sessionState !== apiState) {
              nextRuntime[session.id] = {
                ...prev,
                sessionState: apiState as SessionRuntimeState["sessionState"],
              };
              runtimeChanged = true;
            }
          }
          if (shouldClearStaleRunning) {
            nextRecentCompletionStartedAt[session.id] = Date.now();
            recentCompletionChanged = true;
            if (state.activeSessionId !== session.id && nextCompletedUnread[session.id] !== true) {
              nextCompletedUnread[session.id] = true;
              completedUnreadChanged = true;
            }
          }
        }
      }

      const patch: Partial<SessionStoreState> = {};
      if (runtimeChanged) patch.runtimeBySessionId = nextRuntime;
      if (recentCompletionChanged) {
        patch.recentCompletionStartedAtBySessionId = nextRecentCompletionStartedAt;
      }
      if (completedUnreadChanged) patch.completedUnreadBySessionId = nextCompletedUnread;
      return patch;
    });
  } catch {
    // Silently ignore polling errors
  }
}

function deleteSessionFromGroups(groups: SessionGroup[], sessionId: string): SessionGroup[] {
  return groups
    .map((group) => ({
      ...group,
      sessions: group.sessions.filter((session) => session.id !== sessionId),
    }))
    .filter((group) => group.sessions.length > 0);
}

function applySessionUpsert(
  state: SessionStoreState,
  session: SessionSummary,
): Partial<SessionStoreState> | SessionStoreState {
  const previousSession = findSession(state.groups, session.id);
  const nextGroups = upsertSessionIntoGroups(state.groups, session);
  const previousRuntime = state.runtimeBySessionId[session.id] ?? {
    ...defaultRuntimeState,
    sessionState: previousSession?.session_state ?? "idle",
  };
  const keepWsState =
    previousRuntime.wsState === "connected" || previousRuntime.wsState === "connecting";
  const nextRuntimeBySessionId = {
    ...state.runtimeBySessionId,
    [session.id]: {
      sessionState: keepWsState ? previousRuntime.sessionState : session.session_state,
      wsState: previousRuntime.wsState,
      lastError: previousRuntime.lastError,
    },
  };

  const patch: Partial<SessionStoreState> = {
    groups: nextGroups,
    collapsedByWorkDir: mergeCollapseState(nextGroups, state.collapsedByWorkDir),
    runtimeBySessionId: nextRuntimeBySessionId,
  };

  if (
    previousSession !== null &&
    previousSession.updated_at < session.updated_at &&
    state.activeSessionId !== session.id &&
    session.session_state === "idle"
  ) {
    patch.completedUnreadBySessionId = {
      ...state.completedUnreadBySessionId,
      [session.id]: true,
    };
  }

  // Only trigger the completion animation from session-list upserts when
  // the session WebSocket is NOT active.  When the WS is connected, the
  // task.finish event handled by handleWsEvent will fire the animation
  // exactly once.  Without this guard the upsert fires repeatedly because
  // keepWsState preserves the WS-driven "running" sessionState while the
  // API already reports "idle", re-triggering the condition on every push.
  if (
    !keepWsState &&
    previousSession !== null &&
    previousRuntime.sessionState !== "idle" &&
    session.session_state === "idle"
  ) {
    patch.recentCompletionStartedAtBySessionId = {
      ...state.recentCompletionStartedAtBySessionId,
      [session.id]: Date.now(),
    };
    if (state.activeSessionId !== session.id) {
      patch.completedUnreadBySessionId = {
        ...(patch.completedUnreadBySessionId ?? state.completedUnreadBySessionId),
        [session.id]: true,
      };
    }
  }

  return patch;
}

function handleSessionListEvent(payload: SessionListWsEvent, set: SetState): void {
  if (payload.type === "session.deleted") {
    set((state) => ({
      groups: deleteSessionFromGroups(state.groups, payload.session_id),
      runtimeBySessionId: Object.fromEntries(
        Object.entries(state.runtimeBySessionId).filter(
          ([sessionId]) => sessionId !== payload.session_id,
        ),
      ),
    }));
    return;
  }

  if (payload.session === undefined || payload.session === null) {
    return;
  }

  const session = normalizeSessionSummary(payload.session);
  set((state) => applySessionUpsert(state, session));
}

function connectSessionStream(set: SetState): void {
  if (sessionStream !== null) {
    return;
  }
  sessionStream = connectSessionListWs({
    onEvent: (payload) => {
      handleSessionListEvent(payload, set);
    },
    onClose: () => {
      sessionStream = null;
      if (sessionStreamReconnectTimer !== null) {
        return;
      }
      sessionStreamReconnectTimer = window.setTimeout(() => {
        sessionStreamReconnectTimer = null;
        connectSessionStream(set);
      }, 1000);
    },
  });
}

function pushSessionUrl(sessionId: ActiveSessionId): void {
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

function closeActiveConnectionIfNeeded(nextSessionId: string | null): void {
  if (activeConnection === null) {
    return;
  }
  if (nextSessionId !== null && activeConnection.sessionId === nextSessionId) {
    return;
  }
  activeConnection.connection.close();
  activeConnection = null;
}

function upsertSessionIntoGroups(groups: SessionGroup[], session: SessionSummary): SessionGroup[] {
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

function patchRuntimeByEvent(
  current: Record<string, SessionRuntimeState>,
  sessionId: string,
  eventType: string,
): Record<string, SessionRuntimeState> {
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

function patchPendingInteractionsByEvent(
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

function openSessionWs(sessionId: string, get: () => SessionStoreState, set: SetState): void {
  const runtime = get().runtimeBySessionId[sessionId] ?? defaultRuntimeState;
  if (
    activeConnection?.sessionId === sessionId &&
    (runtime.wsState === "connected" || runtime.wsState === "connecting")
  ) {
    return;
  }

  closeActiveConnectionIfNeeded(sessionId);

  set((state) => ({
    runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
      wsState: "connecting",
      lastError: null,
    }),
  }));

  const connection = connectSessionWs(sessionId, {
    onOpen: () => {
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
          wsState: "connected",
          lastError: null,
        }),
      }));
      void pollRuntimeStates(get, set);
    },
    onClose: () => {
      if (activeConnection?.connection === connection) {
        activeConnection = null;
      }
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
          wsState: "disconnected",
        }),
      }));
    },
    onErrorFrame: (errorFrame) => {
      handleWsError(errorFrame, sessionId, set);
    },
    onEvent: (eventEnvelope) => {
      handleWsEvent(sessionId, eventEnvelope, get, set);
    },
  });

  activeConnection = { sessionId, connection };
}

function handleWsError(errorFrame: WsErrorFrame, sessionId: string, set: SetState): void {
  const fatal =
    errorFrame.code === "session_not_found" || errorFrame.code === "session_init_failed";
  set((state) => {
    const nextRuntimeBySessionId = updateRuntimeState(state.runtimeBySessionId, sessionId, {
      wsState: fatal ? "disconnected" : (state.runtimeBySessionId[sessionId]?.wsState ?? "idle"),
      lastError: `${errorFrame.code}: ${errorFrame.message}`,
    });
    if (nextRuntimeBySessionId === state.runtimeBySessionId) {
      return state;
    }
    return {
      runtimeBySessionId: nextRuntimeBySessionId,
    };
  });
}

async function loadSessionHistory(sessionId: string): Promise<void> {
  const history = await fetchSessionHistory(sessionId);
  useMessageStore.getState().loadHistoryFromEvents(sessionId, history.events);
}

function hasReusableConnection(sessionId: string, state: SessionStoreState): boolean {
  const runtime = state.runtimeBySessionId[sessionId] ?? defaultRuntimeState;
  return (
    activeConnection?.sessionId === sessionId &&
    (runtime.wsState === "connected" || runtime.wsState === "connecting")
  );
}

function handleWsEvent(
  rootSessionId: string,
  eventEnvelope: WsEventEnvelope,
  get: () => SessionStoreState,
  set: SetState,
): void {
  const targetSessionId = eventEnvelope.session_id;
  set((state) => {
    const currentRuntime = state.runtimeBySessionId[targetSessionId] ?? defaultRuntimeState;
    const nextRuntimeBySessionId = patchRuntimeByEvent(
      state.runtimeBySessionId,
      targetSessionId,
      eventEnvelope.event_type,
    );
    const nextPendingInteractionsBySessionId = patchPendingInteractionsByEvent(
      state.pendingInteractionsBySessionId,
      targetSessionId,
      eventEnvelope.event_type,
      eventEnvelope.event ?? {},
    );
    const shouldMarkCompletedUnread =
      eventEnvelope.event_type === "task.finish" &&
      state.activeSessionId !== targetSessionId &&
      state.completedUnreadBySessionId[targetSessionId] !== true;
    const shouldRecordRecentCompletion =
      eventEnvelope.event_type === "task.finish" && currentRuntime.sessionState === "running";

    if (
      nextRuntimeBySessionId === state.runtimeBySessionId &&
      nextPendingInteractionsBySessionId === state.pendingInteractionsBySessionId &&
      !shouldRecordRecentCompletion &&
      !shouldMarkCompletedUnread
    ) {
      return state;
    }

    return {
      runtimeBySessionId: nextRuntimeBySessionId,
      pendingInteractionsBySessionId: nextPendingInteractionsBySessionId,
      recentCompletionStartedAtBySessionId: shouldRecordRecentCompletion
        ? {
            ...state.recentCompletionStartedAtBySessionId,
            [targetSessionId]: Date.now(),
          }
        : state.recentCompletionStartedAtBySessionId,
      completedUnreadBySessionId: shouldMarkCompletedUnread
        ? {
            ...state.completedUnreadBySessionId,
            [targetSessionId]: true,
          }
        : state.completedUnreadBySessionId,
    };
  });

  const wsTimestamp = typeof eventEnvelope.timestamp === "number" ? eventEnvelope.timestamp : null;
  const queuedEvents: MessageStoreEvent[] = [
    {
      sessionId: rootSessionId,
      eventType: eventEnvelope.event_type,
      event: eventEnvelope.event ?? {},
      timestamp: wsTimestamp,
    },
  ];
  if (targetSessionId !== rootSessionId) {
    queuedEvents.push({
      sessionId: targetSessionId,
      eventType: eventEnvelope.event_type,
      event: eventEnvelope.event ?? {},
      timestamp: wsTimestamp,
    });
  }
  queueMessageEvents(queuedEvents);

  if (eventEnvelope.event_type !== "task.finish") {
    return;
  }

  const currentState = get();
  const group = currentState.groups.find((item) =>
    item.sessions.some((session) => session.id === targetSessionId),
  );
  if (group === undefined) {
    return;
  }

  const original = group.sessions.find((item) => item.id === targetSessionId);
  if (original === undefined) {
    return;
  }

  const updatedSession: SessionSummary = {
    ...original,
    updated_at: Date.now() / 1000,
  };
  set((state) => ({
    groups: upsertSessionIntoGroups(state.groups, updatedSession),
  }));
}

type SetState = (
  partial:
    | SessionStoreState
    | Partial<SessionStoreState>
    | ((state: SessionStoreState) => SessionStoreState | Partial<SessionStoreState>),
) => void;

function mergeCollapseState(
  groups: SessionGroup[],
  collapsedByWorkDir: Record<string, boolean>,
): Record<string, boolean> {
  const next: Record<string, boolean> = { ...collapsedByWorkDir };
  for (const group of groups) {
    if (next[group.work_dir] === undefined) {
      next[group.work_dir] = false;
    }
  }
  return next;
}

function findSession(groups: SessionGroup[], sessionId: string): SessionSummary | null {
  for (const group of groups) {
    const session = group.sessions.find((item) => item.id === sessionId);
    if (session !== undefined) {
      return session;
    }
  }
  return null;
}

export const useSessionStore = create<SessionStoreState>((set, get) => ({
  groups: [],
  activeSessionId: "draft",
  draftWorkDir: "",
  loading: false,
  loadError: null,
  collapsedByWorkDir: loadCollapsedByWorkDir(),
  runtimeBySessionId: {},
  recentCompletionStartedAtBySessionId: {},
  completedUnreadBySessionId: {},
  pendingInteractionsBySessionId: {},
  initialized: false,
  init: async () => {
    if (get().initialized) {
      return;
    }
    await get().refreshSessions();

    const match = window.location.pathname.match(/^\/session\/([a-f0-9]+)(?:\/agent\/[a-f0-9]+)?$/);
    if (match) {
      const urlSessionId = match[1];
      if (findSession(get().groups, urlSessionId)) {
        await get().selectSession(urlSessionId);
      } else {
        history.replaceState(null, "", "/");
      }
    }

    set({ initialized: true });
    connectSessionStream(set);
  },
  refreshSessions: async () => {
    set({ loading: true, loadError: null });
    try {
      const groups = await fetchSessionGroups();
      set((state) => ({
        groups,
        loading: false,
        draftWorkDir: state.draftWorkDir,
        collapsedByWorkDir: mergeCollapseState(groups, state.collapsedByWorkDir),
        runtimeBySessionId: groups.reduce<Record<string, SessionRuntimeState>>((acc, group) => {
          for (const session of group.sessions) {
            const previous = state.runtimeBySessionId[session.id];
            const previousWsState = previous?.wsState;
            const shouldKeepPrevious =
              previous !== undefined &&
              (previousWsState === "connected" || previousWsState === "connecting");
            acc[session.id] = {
              sessionState: shouldKeepPrevious ? previous.sessionState : session.session_state,
              wsState: previous?.wsState ?? "idle",
              lastError: previous?.lastError ?? null,
            };
          }
          return acc;
        }, {}),
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set({ loading: false, loadError: message });
    }
  },
  toggleGroup: (workDir: string) => {
    set((state) => {
      const collapsedByWorkDir = {
        ...state.collapsedByWorkDir,
        [workDir]: !(state.collapsedByWorkDir[workDir] ?? false),
      };
      persistCollapsedByWorkDir(collapsedByWorkDir);
      return { collapsedByWorkDir };
    });
  },
  setSessionArchived: async (sessionId: string, archived: boolean) => {
    if (archived) {
      await archiveSession(sessionId);
    } else {
      await unarchiveSession(sessionId);
    }

    set((state) => ({
      groups: state.groups
        .map((group) => ({
          ...group,
          sessions: group.sessions
            .map((session) =>
              session.id === sessionId
                ? { ...session, archived, updated_at: Date.now() / 1000 }
                : session,
            )
            .sort((a, b) => b.updated_at - a.updated_at),
        }))
        .filter((group) => group.sessions.length > 0),
    }));
  },
  archiveCleanupSessions: async () => {
    const archivedCount = await archiveCleanupSessionsRequest();
    await get().refreshSessions();
    return archivedCount;
  },
  selectDraft: (workDir?: string) => {
    const activeSession =
      get().activeSessionId === "draft" ? null : findSession(get().groups, get().activeSessionId);
    const nextDraftWorkDir = workDir?.trim() ?? "";
    closeActiveConnectionIfNeeded(null);
    set((state) => ({
      activeSessionId: "draft",
      draftWorkDir: nextDraftWorkDir || activeSession?.work_dir || state.draftWorkDir,
    }));
    pushSessionUrl("draft");
  },
  setDraftWorkDir: (workDir: string) => {
    set({ draftWorkDir: workDir });
  },
  selectSession: async (sessionId: string) => {
    const currentState = get();
    const currentRuntime = currentState.runtimeBySessionId[sessionId] ?? defaultRuntimeState;
    const sameActiveSession = currentState.activeSessionId === sessionId;
    const reusableConnection = hasReusableConnection(sessionId, currentState);
    const isStreamingSession =
      currentRuntime.sessionState === "running" ||
      currentRuntime.sessionState === "waiting_user_input";

    if (sameActiveSession && isStreamingSession) {
      if (!reusableConnection) {
        openSessionWs(sessionId, get, set);
      }
      pushSessionUrl(sessionId);
      return;
    }

    pushSessionUrl(sessionId);
    set((state) => ({
      activeSessionId: sessionId,
      completedUnreadBySessionId: {
        ...state.completedUnreadBySessionId,
        [sessionId]: false,
      },
      runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
        wsState: reusableConnection ? currentRuntime.wsState : "connecting",
        lastError: null,
      }),
    }));

    try {
      await loadSessionHistory(sessionId);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
          wsState: "disconnected",
          lastError: message,
        }),
      }));
    }

    if (!reusableConnection) {
      openSessionWs(sessionId, get, set);
    }
  },
  refreshSession: async (sessionId: string) => {
    const currentState = get();
    const runtime = currentState.runtimeBySessionId[sessionId] ?? defaultRuntimeState;
    const isStreamingSession =
      runtime.sessionState === "running" || runtime.sessionState === "waiting_user_input";

    if (isStreamingSession) {
      return;
    }

    set((state) => ({
      runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
        lastError: null,
      }),
    }));

    try {
      await loadSessionHistory(sessionId);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
          lastError: message,
        }),
      }));
      return;
    }

    if (!hasReusableConnection(sessionId, get())) {
      openSessionWs(sessionId, get, set);
    }
  },
  createSessionFromDraft: async (
    firstMessage: string,
    workDir?: string,
    modelName?: string | null,
    images?: MessageImagePart[],
  ) => {
    const normalizedMessage = firstMessage.trim();
    const normalizedImages = images?.length ? images : undefined;
    const normalizedWorkDir = workDir?.trim() || undefined;
    const nowSeconds = Date.now() / 1000;
    const { session_id: sessionId } = await createSession(normalizedWorkDir);
    const fallbackWorkDir = normalizedWorkDir ?? "";
    const selectedSession = findSession(get().groups, sessionId);
    const sessionSummary: SessionSummary = selectedSession ?? {
      id: sessionId,
      created_at: nowSeconds,
      updated_at: nowSeconds,
      work_dir: fallbackWorkDir,
      title: null,
      user_messages: normalizedMessage.length > 0 ? [normalizedMessage] : [],
      messages_count: 0,
      model_name: null,
      session_state: "idle",
      read_only: false,
      archived: false,
      todos: [],
      file_change_summary: {
        created_files: [],
        edited_files: [],
        diff_lines_added: 0,
        diff_lines_removed: 0,
        file_diffs: {},
      },
    };

    set((state) => ({
      groups: upsertSessionIntoGroups(state.groups, sessionSummary),
      activeSessionId: sessionId,
      runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
        wsState: "connecting",
        sessionState: "idle",
        lastError: null,
      }),
    }));
    pushSessionUrl(sessionId);

    openSessionWs(sessionId, get, set);
    const selectedModel = modelName?.trim() ?? "";
    if (selectedModel.length > 0) {
      activeConnection?.connection.send({
        type: "model_request",
        preferred: selectedModel,
        save_as_default: false,
      });
    }
    activeConnection?.connection.send({
      type: "message",
      text: normalizedMessage,
      images: normalizedImages,
    });
    return sessionId;
  },
  requestModel: async (sessionId: string, preferred: string, saveAsDefault = false) => {
    const normalizedPreferred = preferred.trim();
    if (normalizedPreferred.length === 0) {
      return;
    }
    if (activeConnection?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    activeConnection?.connection.send({
      type: "model_request",
      preferred: normalizedPreferred,
      save_as_default: saveAsDefault,
    });
  },
  sendMessage: async (sessionId: string, text: string, images?: MessageImagePart[]) => {
    const normalizedText = text.trim();
    const normalizedImages = images?.length ? images : undefined;
    if (normalizedText.length === 0 && normalizedImages === undefined) {
      return;
    }
    if (activeConnection?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    activeConnection?.connection.send({
      type: "message",
      text: normalizedText,
      images: normalizedImages,
    });
  },
  compactSession: async (sessionId: string, focus: string | null) => {
    if (activeConnection?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    activeConnection?.connection.send({
      type: "compact",
      focus: focus ?? undefined,
    });
  },
  interruptSession: async (sessionId: string) => {
    if (activeConnection?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    activeConnection?.connection.send({ type: "interrupt" });
  },
  respondInteraction: async (
    sessionId: string,
    requestId: string,
    response: UserInteractionResponse,
  ) => {
    if (activeConnection?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    activeConnection?.connection.send({
      type: "respond",
      request_id: requestId,
      status: response.status,
      payload: response.payload,
    });
  },
}));
