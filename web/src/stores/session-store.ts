import { create } from "zustand";

import {
  archiveCleanupSessions as archiveCleanupSessionsRequest,
  archiveSession,
  createSession,
  fetchSessionGroups,
  fetchSessionHistory,
  unarchiveSession,
} from "@/api/client";
import type { PendingUserInteractionRequest, UserInteractionResponse } from "@/types/interaction";
import type {
  ActiveSessionId,
  SessionGroup,
  SessionRuntimeState,
  SessionSummary,
} from "@/types/session";
import type { MessageImagePart } from "@/types/message";
import { useMessageStore } from "./message-store";
import {
  defaultRuntimeState,
  findSession,
  loadCollapsedByWorkDir,
  mergeCollapseState,
  persistCollapsedByWorkDir,
  pushSessionUrl,
  updateRuntimeState,
  upsertSessionIntoGroups,
} from "./session-helpers";
import {
  closeActiveConnectionIfNeeded,
  connectSessionStream,
  getActiveConnection,
  hasReusableConnection,
  markOptimisticUserMessage,
  openSessionWs,
} from "./session-ws";

export interface SessionStoreState {
  groups: SessionGroup[];
  activeSessionId: ActiveSessionId;
  draftWorkDir: string;
  loading: boolean;
  loadError: string | null;
  collapsedByWorkDir: Record<string, boolean>;
  runtimeBySessionId: Partial<Record<string, SessionRuntimeState>>;
  recentCompletionStartedAtBySessionId: Record<string, number>;
  completedUnreadBySessionId: Record<string, boolean>;
  pendingInteractionsBySessionId: Record<string, PendingUserInteractionRequest[]>;
  initialized: boolean;
  init: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  toggleGroup: (workDir: string) => void;
  setSessionArchived: (sessionId: string, archived: boolean) => Promise<void>;
  archiveCleanupSessions: (cutoffSeconds: number) => Promise<number>;
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

export type SetState = (
  partial:
    | SessionStoreState
    | Partial<SessionStoreState>
    | ((state: SessionStoreState) => SessionStoreState | Partial<SessionStoreState>),
) => void;

let initPromise: Promise<void> | null = null;

async function loadSessionHistory(sessionId: string): Promise<void> {
  const history = await fetchSessionHistory(sessionId);
  useMessageStore.getState().loadHistoryFromEvents(sessionId, history.events);
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
    if (initPromise) {
      await initPromise;
      return;
    }

    initPromise = (async () => {
      await get().refreshSessions();

      // Default to ~/Desktop for first-time users with no session history
      if (get().groups.length === 0 && get().draftWorkDir.length === 0) {
        set({ draftWorkDir: "~/Desktop" });
      }

      const match = window.location.pathname.match(
        /^\/session\/([a-f0-9]+)(?:\/agent\/[a-f0-9]+)?$/,
      );
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
    })();

    try {
      await initPromise;
    } finally {
      initPromise = null;
    }
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
  archiveCleanupSessions: async (cutoffSeconds: number) => {
    const archivedCount = await archiveCleanupSessionsRequest(cutoffSeconds);
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
        // Reload history to recover any events missed during the WS gap, then reconnect.
        await loadSessionHistory(sessionId).catch(() => {});
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

    // Optimistically inject the user's first message into the message store
    // BEFORE switching activeSessionId so that MessageList renders it
    // immediately instead of showing an empty loading state.
    if (normalizedMessage.length > 0 || normalizedImages) {
      useMessageStore.getState().handleEvent(
        sessionId,
        "user.message",
        {
          content: normalizedMessage,
          images: normalizedImages,
          session_id: sessionId,
        },
        nowSeconds,
      );
      markOptimisticUserMessage(sessionId);
    }

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
      getActiveConnection()?.connection.send({
        type: "model_request",
        preferred: selectedModel,
        save_as_default: false,
      });
    }
    getActiveConnection()?.connection.send({
      type: "message",
      text: normalizedMessage,
      images: normalizedImages,
    });
    return sessionId;
  },
  requestModel: (sessionId: string, preferred: string, saveAsDefault = false): Promise<void> => {
    const normalizedPreferred = preferred.trim();
    if (normalizedPreferred.length === 0) {
      return Promise.resolve();
    }
    if (getActiveConnection()?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    getActiveConnection()?.connection.send({
      type: "model_request",
      preferred: normalizedPreferred,
      save_as_default: saveAsDefault,
    });
    return Promise.resolve();
  },
  sendMessage: (sessionId: string, text: string, images?: MessageImagePart[]): Promise<void> => {
    const normalizedText = text.trim();
    const normalizedImages = images?.length ? images : undefined;
    if (normalizedText.length === 0 && normalizedImages === undefined) {
      return Promise.resolve();
    }
    if (getActiveConnection()?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    getActiveConnection()?.connection.send({
      type: "message",
      text: normalizedText,
      images: normalizedImages,
    });
    return Promise.resolve();
  },
  compactSession: (sessionId: string, focus: string | null): Promise<void> => {
    if (getActiveConnection()?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    getActiveConnection()?.connection.send({
      type: "compact",
      focus: focus ?? undefined,
    });
    return Promise.resolve();
  },
  interruptSession: (sessionId: string): Promise<void> => {
    if (getActiveConnection()?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    getActiveConnection()?.connection.send({ type: "interrupt" });
    return Promise.resolve();
  },
  respondInteraction: (
    sessionId: string,
    requestId: string,
    response: UserInteractionResponse,
  ): Promise<void> => {
    if (getActiveConnection()?.sessionId !== sessionId) {
      openSessionWs(sessionId, get, set);
    }
    getActiveConnection()?.connection.send({
      type: "respond",
      request_id: requestId,
      status: response.status,
      payload: response.payload,
    });
    return Promise.resolve();
  },
}));
