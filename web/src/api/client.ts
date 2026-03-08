import type { SessionGroup, SessionHistoryResponse } from "../types/session";

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

export async function fetchSessionGroups(): Promise<SessionGroup[]> {
  const result = await requestJson<SessionGroupsResponse>("/api/sessions");
  return result.groups;
}

export async function fetchSessionHistory(sessionId: string): Promise<SessionHistoryResponse> {
  return await requestJson<SessionHistoryResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/history`,
  );
}

export interface RunningSessionState {
  session_state: string;
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

export function buildFileApiUrl(path: string): string {
  return `/api/files?${new URLSearchParams({ path }).toString()}`;
}
