import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import { useSessionStore } from "../../stores/session-store";
import { DraftWorkspacePicker } from "./DraftWorkspacePicker";
import { SessionStatusBar } from "./SessionStatusBar";

function uniqueWorkspaces(workspaces: string[]): string[] {
  return [...new Set(workspaces.filter((item) => item.trim().length > 0))];
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
          <DraftWorkspacePicker
            draftWorkDir={draftWorkDir}
            normalizedDraftWorkDir={normalizedDraftWorkDir}
            workspaceMenuOpen={workspaceMenuOpen}
            filteredWorkspaceOptions={filteredWorkspaceOptions}
            workspacePickerRef={workspacePickerRef}
            setDraftWorkDir={setDraftWorkDir}
            setWorkspaceMenuOpen={setWorkspaceMenuOpen}
          />
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
            className="max-h-64 min-h-[72px] w-full resize-y border-0 bg-transparent px-2 py-1 text-sm leading-6 text-neutral-800 outline-none placeholder:text-neutral-400"
          />

          <div className="mt-2 flex items-center justify-between gap-3 border-t border-neutral-100 px-2 pt-2">
            <div className="text-2xs text-neutral-400">
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
