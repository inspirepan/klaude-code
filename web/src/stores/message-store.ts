import { create } from "zustand";

import type { MessageItem } from "../types/message";
import type { ReplayEventEnvelope } from "../types/session";
import { createInitialState, reduceBatch, reduceEvent, type ReducerState } from "./event-reducer";

export interface MessageStoreEvent {
  sessionId: string;
  eventType: string;
  event: Record<string, unknown>;
  timestamp?: number | null;
}

interface MessageStoreState {
  messagesBySessionId: Record<string, MessageItem[]>;
  reducerStateBySessionId: Partial<Record<string, ReducerState>>;
  loadHistoryFromEvents: (sessionId: string, events: ReplayEventEnvelope[]) => void;
  handleEvents: (events: MessageStoreEvent[]) => void;
  handleEvent: (
    sessionId: string,
    eventType: string,
    event: Record<string, unknown>,
    timestamp?: number | null,
  ) => void;
  clearSession: (sessionId: string) => void;
}

export const useMessageStore = create<MessageStoreState>((set, get) => ({
  messagesBySessionId: {},
  reducerStateBySessionId: {},

  loadHistoryFromEvents: (sessionId, events) => {
    const reducerState = reduceBatch(events);
    set((state) => ({
      messagesBySessionId: {
        ...state.messagesBySessionId,
        [sessionId]: reducerState.items,
      },
      reducerStateBySessionId: {
        ...state.reducerStateBySessionId,
        [sessionId]: reducerState,
      },
    }));
  },

  handleEvents: (events) => {
    if (events.length === 0) {
      return;
    }

    set((state) => {
      const baseReducerStateBySessionId = new Map<string, ReducerState>();
      const nextReducerStateBySessionId = new Map<string, ReducerState>();

      for (const { sessionId, eventType, event, timestamp } of events) {
        let currentReducerState = nextReducerStateBySessionId.get(sessionId);
        if (currentReducerState === undefined) {
          currentReducerState = state.reducerStateBySessionId[sessionId] ?? createInitialState();
          baseReducerStateBySessionId.set(sessionId, currentReducerState);
        }

        nextReducerStateBySessionId.set(
          sessionId,
          reduceEvent(currentReducerState, eventType, event, timestamp ?? null),
        );
      }

      let changed = false;
      let nextMessages = state.messagesBySessionId;
      let nextReducerState = state.reducerStateBySessionId;

      for (const [sessionId, reducedState] of nextReducerStateBySessionId) {
        const baseState = baseReducerStateBySessionId.get(sessionId);
        if (baseState === undefined || reducedState === baseState) {
          continue;
        }

        if (!changed) {
          changed = true;
          nextMessages = { ...state.messagesBySessionId };
          nextReducerState = { ...state.reducerStateBySessionId };
        }

        nextMessages[sessionId] = reducedState.items;
        nextReducerState[sessionId] = reducedState;
      }

      if (!changed) {
        return state;
      }

      return {
        messagesBySessionId: nextMessages,
        reducerStateBySessionId: nextReducerState,
      };
    });
  },

  handleEvent: (sessionId, eventType, event, timestamp) => {
    get().handleEvents([{ sessionId, eventType, event, timestamp }]);
  },

  clearSession: (sessionId) => {
    set((state) => {
      const { [sessionId]: _msgs, ...restMessages } = state.messagesBySessionId;
      const { [sessionId]: _rs, ...restReducer } = state.reducerStateBySessionId;
      return {
        messagesBySessionId: restMessages,
        reducerStateBySessionId: restReducer,
      };
    });
  },
}));
