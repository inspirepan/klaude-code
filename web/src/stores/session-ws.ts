import {
  fetchRunningSessions,
  fetchSessionHistory,
  normalizeSessionSummary,
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
import type { SessionRuntimeState, SessionSummary } from "../types/session";
import { useMessageStore, type MessageStoreEvent } from "./message-store";
import {
  defaultRuntimeState,
  deleteSessionFromGroups,
  findSession,
  patchPendingInteractionsByEvent,
  patchRuntimeByEvent,
  updateRuntimeState,
  upsertSessionIntoGroups,
  mergeCollapseState,
} from "./session-helpers";
import type { SessionStoreState, SetState } from "./session-store";

interface ActiveConnection {
  sessionId: string;
  connection: SessionWsConnection;
}

let activeConnection: ActiveConnection | null = null;
let sessionStream: SessionWsConnection | null = null;
let sessionStreamReconnectTimer: ReturnType<typeof setTimeout> | null = null;
let pendingMessageEvents: MessageStoreEvent[] = [];
let pendingMessageEventsFrame = 0;

// Tracks sessions where the first user message was optimistically pre-populated
// into the message store before the WebSocket connection was established.  When
// the server echoes the `user.message` event back we skip forwarding it to the
// message store so the message is not duplicated.
const optimisticUserMessageSessionIds = new Set<string>();

export function markOptimisticUserMessage(sessionId: string): void {
  optimisticUserMessageSessionIds.add(sessionId);
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

export async function pollRuntimeStates(
  get: () => SessionStoreState,
  set: SetState,
): Promise<void> {
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
          const running = states[session.id] as RunningSessionState | undefined;
          const apiState = (running?.session_state ??
            session.session_state) as SessionRuntimeState["sessionState"];
          const prev = nextRuntime[session.id] ?? {
            ...defaultRuntimeState,
            sessionState: session.session_state,
          };
          if (!(session.id in nextRuntime)) {
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
                sessionState: apiState,
              };
              runtimeChanged = true;
            }
          }
          if (shouldClearStaleRunning) {
            nextRecentCompletionStartedAt[session.id] = Date.now();
            recentCompletionChanged = true;
            if (state.activeSessionId !== session.id && !nextCompletedUnread[session.id]) {
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

export function connectSessionStream(set: SetState): void {
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
      sessionStreamReconnectTimer = setTimeout(() => {
        sessionStreamReconnectTimer = null;
        connectSessionStream(set);
      }, 1000);
    },
  });
}

export function closeActiveConnectionIfNeeded(nextSessionId: string | null): void {
  if (activeConnection === null) {
    return;
  }
  if (nextSessionId !== null && activeConnection.sessionId === nextSessionId) {
    return;
  }
  activeConnection.connection.close();
  activeConnection = null;
}

export function hasReusableConnection(sessionId: string, state: SessionStoreState): boolean {
  const runtime = state.runtimeBySessionId[sessionId] ?? defaultRuntimeState;
  return (
    activeConnection?.sessionId === sessionId &&
    (runtime.wsState === "connected" || runtime.wsState === "connecting")
  );
}

function handleWsError(errorFrame: WsErrorFrame, sessionId: string, set: SetState): void {
  const fatal =
    errorFrame.code === "session_not_found" || errorFrame.code === "session_init_failed";
  set((state) => {
    const currentRuntime = state.runtimeBySessionId[sessionId];
    const nextRuntimeBySessionId = updateRuntimeState(state.runtimeBySessionId, sessionId, {
      wsState: fatal ? "disconnected" : (currentRuntime?.wsState ?? "idle"),
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
      !state.completedUnreadBySessionId[targetSessionId];
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

  // Skip forwarding the server echo of a user.message that was already
  // optimistically injected into the message store during session creation.
  const skipMessageStore =
    eventEnvelope.event_type === "user.message" &&
    optimisticUserMessageSessionIds.delete(rootSessionId);

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
  if (!skipMessageStore) {
    queueMessageEvents(queuedEvents);
  }

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

export function openSessionWs(
  sessionId: string,
  get: () => SessionStoreState,
  set: SetState,
): void {
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
      // Reload history to recover events that may have been missed during the
      // WS gap (e.g. queue overflow on the backend).  Fire-and-forget; only
      // bother if this session is still the active one.
      if (get().activeSessionId === sessionId) {
        void fetchSessionHistory(sessionId)
          .then((history) => {
            useMessageStore.getState().loadHistoryFromEvents(sessionId, history.events);
          })
          .catch(() => {});
      }
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

export function getActiveConnection(): ActiveConnection | null {
  return activeConnection;
}
