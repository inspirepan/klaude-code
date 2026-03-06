import { create } from "zustand";

import type { MessageItem } from "../types/message";
import type { ReplayEventEnvelope } from "../types/session";
import { createInitialState, reduceBatch, reduceEvent, type ReducerState } from "./event-reducer";

interface MessageStoreState {
  messagesBySessionId: Record<string, MessageItem[]>;
  reducerStateBySessionId: Record<string, ReducerState>;
  loadHistoryFromEvents: (sessionId: string, events: ReplayEventEnvelope[]) => void;
  handleEvent: (
    sessionId: string,
    eventType: string,
    event: Record<string, unknown>,
    timestamp?: number | null,
  ) => void;
  clearSession: (sessionId: string) => void;
}

export const useMessageStore = create<MessageStoreState>((set) => ({
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

  handleEvent: (sessionId, eventType, event, timestamp) => {
    set((state) => {
      const currentReducerState = state.reducerStateBySessionId[sessionId] ?? createInitialState();
      const nextReducerState = reduceEvent(
        currentReducerState,
        eventType,
        event,
        timestamp ?? null,
      );
      if (nextReducerState === currentReducerState) return state;
      return {
        messagesBySessionId: {
          ...state.messagesBySessionId,
          [sessionId]: nextReducerState.items,
        },
        reducerStateBySessionId: {
          ...state.reducerStateBySessionId,
          [sessionId]: nextReducerState,
        },
      };
    });
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
