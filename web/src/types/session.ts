export type SessionId = string;
export type ActiveSessionId = SessionId | "draft";
export type ApiSessionState = "idle" | "running" | "waiting_user_input";

export interface SessionSummary {
  id: SessionId;
  created_at: number;
  updated_at: number;
  work_dir: string;
  title: string | null;
  user_messages: string[];
  messages_count: number;
  model_name: string | null;
  session_state: ApiSessionState;
  archived: boolean;
}

export interface SessionGroup {
  work_dir: string;
  sessions: SessionSummary[];
}

export interface ReplayEventEnvelope {
  event_type: string;
  event: Record<string, unknown>;
  timestamp?: number;
}

export interface SessionHistoryResponse {
  session_id: SessionId;
  events: ReplayEventEnvelope[];
}

export type SessionWsState = "idle" | "connecting" | "connected" | "disconnected";

export interface SessionRuntimeState {
  sessionState: ApiSessionState;
  wsState: SessionWsState;
  lastError: string | null;
}
