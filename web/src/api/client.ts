import type {
  FileChangeSummary,
  SessionGroup,
  SessionHistoryResponse,
  SessionSummary,
} from "../types/session";
import type { MessageImageFilePart } from "../types/message";

interface JsonRequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
}

async function requestJson<T>(path: string, options: JsonRequestOptions = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) {
    const detailText = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detailText}`);
  }

  return (await response.json()) as T;
}

interface SessionGroupsResponse {
  groups: SessionGroup[];
}

function normalizeFileChangeSummary(
  summary: Partial<FileChangeSummary> | null | undefined,
): FileChangeSummary {
  return {
    created_files: Array.isArray(summary?.created_files) ? summary.created_files : [],
    edited_files: Array.isArray(summary?.edited_files) ? summary.edited_files : [],
    diff_lines_added: typeof summary?.diff_lines_added === "number" ? summary.diff_lines_added : 0,
    diff_lines_removed:
      typeof summary?.diff_lines_removed === "number" ? summary.diff_lines_removed : 0,
    file_diffs:
      summary?.file_diffs && typeof summary.file_diffs === "object" ? summary.file_diffs : {},
  };
}

function normalizeSessionSummary(session: SessionSummary): SessionSummary {
  return {
    ...session,
    read_only: session.read_only === true,
    todos: Array.isArray(session.todos) ? session.todos : [],
    file_change_summary: normalizeFileChangeSummary(session.file_change_summary),
  };
}

export async function fetchSessionGroups(): Promise<SessionGroup[]> {
  const result = await requestJson<SessionGroupsResponse>("/api/sessions");
  return result.groups.map((group) => ({
    ...group,
    sessions: group.sessions.map(normalizeSessionSummary),
  }));
}

export async function fetchSessionHistory(sessionId: string): Promise<SessionHistoryResponse> {
  return await requestJson<SessionHistoryResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/history`,
  );
}

export interface RunningSessionState {
  session_state: string;
  read_only: boolean;
  title: string | null;
  user_messages: string[];
}

interface RunningSessionsResponse {
  states: Record<string, RunningSessionState>;
}

export async function fetchRunningSessions(): Promise<Record<string, RunningSessionState>> {
  const result = await requestJson<RunningSessionsResponse>("/api/sessions/running");
  return result.states;
}

interface CreateSessionRequest {
  work_dir?: string;
}

interface CreateSessionResponse {
  session_id: string;
}

export async function createSession(workDir?: string): Promise<CreateSessionResponse> {
  const payload: CreateSessionRequest | undefined =
    workDir === undefined ? undefined : { work_dir: workDir };
  return await requestJson<CreateSessionResponse>("/api/sessions", {
    method: "POST",
    body: payload ?? {},
  });
}

interface ArchiveSessionResponse {
  ok: boolean;
}

export interface ConfigModelSummary {
  name: string;
  provider: string;
  model_name: string;
  model_id: string;
  params: string[];
  is_default: boolean;
}

interface ConfigModelsResponse {
  models: ConfigModelSummary[];
}

export async function archiveSession(sessionId: string): Promise<boolean> {
  const result = await requestJson<ArchiveSessionResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/archive`,
    {
      method: "POST",
      body: {},
    },
  );
  return result.ok;
}

export async function unarchiveSession(sessionId: string): Promise<boolean> {
  const result = await requestJson<ArchiveSessionResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/unarchive`,
    {
      method: "POST",
      body: {},
    },
  );
  return result.ok;
}

export async function fetchConfigModels(): Promise<ConfigModelSummary[]> {
  const result = await requestJson<ConfigModelsResponse>("/api/config/models");
  return result.models;
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result !== "string") {
        reject(new Error("failed to read image file"));
        return;
      }
      resolve(reader.result);
    });
    reader.addEventListener("error", () => {
      reject(reader.error ?? new Error("failed to read image file"));
    });
    reader.readAsDataURL(file);
  });
}

export async function uploadImageAttachment(file: File): Promise<MessageImageFilePart> {
  const dataUrl = await readFileAsDataUrl(file);
  return await requestJson<MessageImageFilePart>("/api/files/images", {
    method: "POST",
    body: {
      data_url: dataUrl,
      file_name: file.name || null,
    },
  });
}

export function buildFileApiUrl(path: string): string {
  return `/api/files?${new URLSearchParams({ path }).toString()}`;
}
