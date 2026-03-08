import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Folder, SendHorizonal } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import { useSessionStore } from "../../stores/session-store";
import { SessionStatusBar } from "./SessionStatusBar";

function uniqueWorkspaces(workspaces: string[]): string[] {
  return [...new Set(workspaces.filter((item) => item.trim().length > 0))];
}

function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((segment) => segment.length > 0);
  return parts[parts.length - 1] ?? workDir;
}

export function MessageComposer(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const draftWorkDir = useSessionStore((state) => state.draftWorkDir);
  const groups = useSessionStore((state) => state.groups);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const createSessionFromDraft = useSessionStore((state) => state.createSessionFromDraft);
  const sendMessage = useSessionStore((state) => state.sendMessage);
  const statusBySessionId = useMessageStore((state) =>
    activeSessionId === "draft"
      ? null
      : (state.reducerStateBySessionId[activeSessionId]?.statusBySessionId ?? null),
  );
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);
  const workspacePickerRef = useRef<HTMLDivElement | null>(null);

  const isDraft = activeSessionId === "draft";
  const runtime = isDraft ? null : (runtimeBySessionId[activeSessionId] ?? null);
  const activeSession = isDraft
    ? null
    : (groups
        .flatMap((group) => group.sessions)
        .find((session) => session.id === activeSessionId) ?? null);
  const workspaceOptions = useMemo(
    () => uniqueWorkspaces(groups.map((group) => group.work_dir)),
    [groups],
  );
  const normalizedDraftWorkDir = draftWorkDir.trim();
  const filteredWorkspaceOptions = useMemo(() => {
    if (normalizedDraftWorkDir.length === 0) {
      return workspaceOptions;
    }
    const query = normalizedDraftWorkDir.toLowerCase();
    return workspaceOptions.filter((workspace) => workspace.toLowerCase().includes(query));
  }, [normalizedDraftWorkDir, workspaceOptions]);
  const normalizedText = text.trim();
  const sessionBusy =
    runtime !== null &&
    (runtime.sessionState !== "idle" ||
      runtime.wsState === "connecting" ||
      runtime.wsState === "disconnected");
  const sessionReadOnly = activeSession?.read_only === true;
  const mainSessionStatus =
    isDraft || statusBySessionId === null ? null : (statusBySessionId[activeSessionId] ?? null);
  const disableSubmit =
    submitting ||
    normalizedText.length === 0 ||
    (isDraft ? normalizedDraftWorkDir.length === 0 : sessionBusy || sessionReadOnly);

  useEffect(() => {
    setText("");
  }, [activeSessionId]);

  useEffect(() => {
    if (!isDraft) {
      setWorkspaceMenuOpen(false);
    }
  }, [isDraft]);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!workspacePickerRef.current?.contains(event.target as Node)) {
        setWorkspaceMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, []);

  const handleSubmit = useCallback(async () => {
    if (disableSubmit) {
      return;
    }

    setSubmitting(true);
    try {
      if (isDraft) {
        await createSessionFromDraft(normalizedText, normalizedDraftWorkDir);
      } else {
        await sendMessage(activeSessionId, normalizedText);
      }
      setText("");
    } finally {
      setSubmitting(false);
    }
  }, [
    activeSessionId,
    createSessionFromDraft,
    disableSubmit,
    isDraft,
    normalizedDraftWorkDir,
    normalizedText,
    sendMessage,
  ]);

  return (
    <div className="shrink-0 border-t border-neutral-200/80 bg-white/95 px-4 py-3 backdrop-blur sm:px-6">
      <div className="mx-auto max-w-4xl space-y-3">
        {!isDraft ? <SessionStatusBar status={mainSessionStatus} runtime={runtime} /> : null}
        {isDraft ? (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
              <label
                htmlFor="draft-workspace"
                className="text-[12px] font-semibold text-neutral-600"
              >
                Workspace
              </label>
              <span className="text-[11px] text-neutral-400">Choose or type a local path</span>
            </div>
            <div ref={workspacePickerRef} className="relative">
              <div
                className={[
                  "flex items-center rounded-2xl border bg-white/95 shadow-sm transition-all",
                  workspaceMenuOpen
                    ? "border-neutral-300 shadow-[0_10px_30px_rgba(0,0,0,0.08)]"
                    : "border-neutral-200 hover:border-neutral-300 hover:bg-white",
                ].join(" ")}
              >
                <div className="pl-3 text-neutral-400">
                  <Folder className="h-4 w-4" />
                </div>
                <input
                  id="draft-workspace"
                  value={draftWorkDir}
                  onFocus={() => {
                    setWorkspaceMenuOpen(true);
                  }}
                  onChange={(event) => {
                    setDraftWorkDir(event.target.value);
                    setWorkspaceMenuOpen(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      setWorkspaceMenuOpen(false);
                    }
                  }}
                  placeholder="/path/to/workspace"
                  className="w-full flex-1 border-0 bg-transparent px-2 py-3 text-[13px] text-neutral-700 outline-none placeholder:text-neutral-400"
                />
                <button
                  type="button"
                  className="mr-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-700"
                  onClick={() => {
                    setWorkspaceMenuOpen((prev) => !prev);
                  }}
                  aria-label="Toggle workspace suggestions"
                >
                  <ChevronDown
                    className={[
                      "h-4 w-4 transition-transform duration-150",
                      workspaceMenuOpen ? "rotate-180" : "rotate-0",
                    ].join(" ")}
                  />
                </button>
              </div>

              {workspaceMenuOpen ? (
                <div className="absolute left-0 right-0 z-20 mt-2 overflow-hidden rounded-2xl border border-neutral-200 bg-white/95 p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.12)] backdrop-blur">
                  <div className="px-2.5 pb-1 pt-1 text-[11px] font-medium uppercase tracking-[0.08em] text-neutral-400">
                    Recent workspaces
                  </div>
                  {filteredWorkspaceOptions.length > 0 ? (
                    <div className="max-h-64 space-y-0.5 overflow-y-auto">
                      {filteredWorkspaceOptions.map((workspace) => {
                        const isSelected = workspace === normalizedDraftWorkDir;
                        return (
                          <button
                            key={workspace}
                            type="button"
                            className={[
                              "flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                              isSelected
                                ? "bg-neutral-100 text-neutral-900"
                                : "text-neutral-700 hover:bg-neutral-50",
                            ].join(" ")}
                            onMouseDown={(event) => {
                              event.preventDefault();
                            }}
                            onClick={() => {
                              setDraftWorkDir(workspace);
                              setWorkspaceMenuOpen(false);
                            }}
                          >
                            <Folder className="mt-0.5 h-4 w-4 shrink-0 text-neutral-400" />
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-[13px] font-medium leading-5 text-neutral-800">
                                {workDirLabel(workspace)}
                              </div>
                              <div className="truncate text-[11px] leading-4 text-neutral-400">
                                {workspace}
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="px-3 py-3 text-[12px] text-neutral-400">
                      No matching workspace. You can still type any local path.
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="rounded-2xl border border-neutral-200 bg-white p-2 shadow-sm">
          <textarea
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing || event.key !== "Enter" || event.shiftKey) {
                return;
              }
              event.preventDefault();
              void handleSubmit();
            }}
            rows={3}
            placeholder={isDraft ? "Message Klaude about this workspace..." : "Send a follow-up..."}
            className="max-h-64 min-h-[72px] w-full resize-y border-0 bg-transparent px-2 py-1 text-[14px] leading-6 text-neutral-800 outline-none placeholder:text-neutral-400"
          />

          <div className="mt-2 flex items-center justify-between gap-3 border-t border-neutral-100 px-2 pt-2">
            <div className="text-[11px] text-neutral-400">
              {isDraft
                ? normalizedDraftWorkDir.length > 0
                  ? normalizedDraftWorkDir
                  : "Pick a workspace before sending"
                : sessionReadOnly
                  ? "This session is running in another process and is read-only"
                  : sessionBusy
                    ? runtime?.sessionState === "running"
                      ? "Current session is still running"
                      : runtime?.wsState === "disconnected"
                        ? "WebSocket is disconnected"
                        : "Session is temporarily unavailable"
                    : "Enter to send, Shift+Enter for newline"}
            </div>
            <button
              type="button"
              onClick={() => {
                void handleSubmit();
              }}
              disabled={disableSubmit}
              className="inline-flex h-9 items-center gap-2 rounded-xl bg-neutral-900 px-3 text-[13px] font-medium text-white transition-colors hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
            >
              <SendHorizonal className="h-4 w-4" />
              <span>{submitting ? "Sending..." : "Send"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
