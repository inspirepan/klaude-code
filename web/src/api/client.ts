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
  return await requestJson<SessionHistoryResponse>(`/api/sessions/${encodeURIComponent(sessionId)}/history`);
}

interface CreateSessionRequest {
  work_dir?: string;
}

interface CreateSessionResponse {
  session_id: string;
}

export async function createSession(workDir?: string): Promise<CreateSessionResponse> {
  const payload: CreateSessionRequest | undefined = workDir === undefined ? undefined : { work_dir: workDir };
  return await requestJson<CreateSessionResponse>("/api/sessions", {
    method: "POST",
    body: payload ?? {},
  });
}
