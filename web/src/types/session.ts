export type SessionId = string;
// eslint-disable-next-line @typescript-eslint/no-redundant-type-constituents -- "draft" documents the sentinel value checked via === "draft" at runtime
export type ActiveSessionId = SessionId | "draft";
export type ApiSessionState = "idle" | "running" | "waiting_user_input";

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface FileDiffStats {
  added: number;
  removed: number;
}

export interface FileChangeSummary {
  created_files: string[];
  edited_files: string[];
  deleted_files: string[];
  diff_lines_added: number;
  diff_lines_removed: number;
  file_diffs: Record<string, FileDiffStats>;
}

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
  read_only: boolean;
  archived: boolean;
  todos: TodoItem[];
  file_change_summary: FileChangeSummary;
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
