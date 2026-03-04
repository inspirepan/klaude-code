import { create } from "zustand";

import { createSession, fetchSessionGroups, fetchSessionHistory } from "../api/client";
import { connectSessionWs, type SessionWsConnection, type WsErrorFrame, type WsEventEnvelope } from "../api/ws";
import type {
  ActiveSessionId,
  SessionGroup,
  SessionRuntimeState,
  SessionSummary,
  SessionWsState,
} from "../types/session";
import { useMessageStore } from "./message-store";

interface SessionStoreState {
  groups: SessionGroup[];
  activeSessionId: ActiveSessionId;
  loading: boolean;
  loadError: string | null;
  collapsedByWorkDir: Record<string, boolean>;
  runtimeBySessionId: Record<string, SessionRuntimeState>;
  initialized: boolean;
  init: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  toggleGroup: (workDir: string) => void;
  selectDraft: () => void;
  selectSession: (sessionId: string) => Promise<void>;
  createSessionFromDraft: (firstMessage: string, workDir?: string) => Promise<string>;
}

interface ActiveConnection {
  sessionId: string;
  connection: SessionWsConnection;
}

let activeConnection: ActiveConnection | null = null;

const defaultRuntimeState: SessionRuntimeState = {
  isRunning: false,
  wsState: "idle",
  lastError: null,
};

function updateRuntimeState(
  current: Record<string, SessionRuntimeState>,
  sessionId: string,
  patch: Partial<SessionRuntimeState>,
): Record<string, SessionRuntimeState> {
  return {
    ...current,
    [sessionId]: {
      ...(current[sessionId] ?? defaultRuntimeState),
      ...patch,
    },
  };
}

function pushSessionUrl(sessionId: ActiveSessionId): void {
  const target = sessionId === "draft" ? "/" : `/session/${sessionId}`;
  if (window.location.pathname !== target) {
    history.pushState(null, "", target);
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

function inferRunningFromHistory(eventTypes: string[]): boolean {
  let runningDepth = 0;
  for (const eventType of eventTypes) {
    if (eventType === "task.start") {
      runningDepth += 1;
      continue;
    }
    if (eventType === "task.finish" && runningDepth > 0) {
      runningDepth -= 1;
    }
  }
  return runningDepth > 0;
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
    return updateRuntimeState(current, sessionId, { isRunning: true });
  }
  if (eventType === "task.finish" || eventType === "operation.finished") {
    return updateRuntimeState(current, sessionId, { isRunning: false });
  }
  return current;
}

function openSessionWs(sessionId: string, get: () => SessionStoreState, set: SetState): void {
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
    },
    onClose: () => {
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
      handleWsEvent(eventEnvelope, get, set);
    },
  });

  activeConnection = { sessionId, connection };
}

function handleWsError(errorFrame: WsErrorFrame, sessionId: string, set: SetState): void {
  set((state) => ({
    runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
      wsState: "disconnected",
      isRunning: false,
      lastError: `${errorFrame.code}: ${errorFrame.message}`,
    }),
  }));
}

function handleWsEvent(eventEnvelope: WsEventEnvelope, get: () => SessionStoreState, set: SetState): void {
  const targetSessionId = eventEnvelope.session_id;
  set((state) => ({
    runtimeBySessionId: patchRuntimeByEvent(state.runtimeBySessionId, targetSessionId, eventEnvelope.event_type),
  }));

  const wsTimestamp = typeof eventEnvelope.timestamp === "number" ? eventEnvelope.timestamp : null;
  useMessageStore
    .getState()
    .handleEvent(targetSessionId, eventEnvelope.event_type, eventEnvelope.event ?? {}, wsTimestamp);

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
  loading: false,
  loadError: null,
  collapsedByWorkDir: {},
  runtimeBySessionId: {},
  initialized: false,
  init: async () => {
    if (get().initialized) {
      return;
    }
    await get().refreshSessions();
    set({ initialized: true });
  },
  refreshSessions: async () => {
    set({ loading: true, loadError: null });
    try {
      const groups = await fetchSessionGroups();
      set((state) => ({
        groups,
        loading: false,
        collapsedByWorkDir: mergeCollapseState(groups, state.collapsedByWorkDir),
        runtimeBySessionId: groups.reduce<Record<string, SessionRuntimeState>>((acc, group) => {
          for (const session of group.sessions) {
            const previous = state.runtimeBySessionId[session.id];
            const apiIsRunning = session.session_state !== "idle";
            const previousWsState = previous?.wsState;
            const shouldKeepPrevious =
              previous !== undefined && (previousWsState === "connected" || previousWsState === "connecting");
            acc[session.id] = {
              isRunning: shouldKeepPrevious ? previous.isRunning : apiIsRunning,
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
    set((state) => ({
      collapsedByWorkDir: {
        ...state.collapsedByWorkDir,
        [workDir]: !(state.collapsedByWorkDir[workDir] ?? false),
      },
    }));
  },
  selectDraft: () => {
    closeActiveConnectionIfNeeded(null);
    set({ activeSessionId: "draft" });
  },
  selectSession: async (sessionId: string) => {
    set((state) => ({
      activeSessionId: sessionId,
      runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
        wsState: "connecting",
        lastError: null,
      }),
    }));

    try {
      const history = await fetchSessionHistory(sessionId);
      const isRunning = inferRunningFromHistory(history.events.map((item) => item.event_type));
      useMessageStore.getState().loadHistoryFromEvents(sessionId, history.events);
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, { isRunning }),
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set((state) => ({
        runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
          wsState: "disconnected",
          lastError: message,
        }),
      }));
    }

    openSessionWs(sessionId, get, set);
  },
  createSessionFromDraft: async (firstMessage: string, workDir?: string) => {
    const nowSeconds = Date.now() / 1000;
    const { session_id: sessionId } = await createSession(workDir);
    const fallbackWorkDir = workDir ?? "";
    const selectedSession = findSession(get().groups, sessionId);
    const sessionSummary: SessionSummary =
      selectedSession ?? {
        id: sessionId,
        created_at: nowSeconds,
        updated_at: nowSeconds,
        work_dir: fallbackWorkDir,
        user_messages: firstMessage.trim().length > 0 ? [firstMessage] : [],
        messages_count: 0,
        model_name: null,
        session_state: "idle",
      };

    set((state) => ({
      groups: upsertSessionIntoGroups(state.groups, sessionSummary),
      activeSessionId: sessionId,
      runtimeBySessionId: updateRuntimeState(state.runtimeBySessionId, sessionId, {
        wsState: "connecting",
        isRunning: false,
        lastError: null,
      }),
    }));

    openSessionWs(sessionId, get, set);
    activeConnection?.connection.send({ type: "message", text: firstMessage });
    return sessionId;
  },
}));
