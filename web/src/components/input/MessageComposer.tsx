import { useCallback, useEffect, useMemo, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { useSessionStore } from "../../stores/session-store";

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
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isDraft = activeSessionId === "draft";
  const runtime = isDraft ? null : (runtimeBySessionId[activeSessionId] ?? null);
  const workspaceOptions = useMemo(
    () => uniqueWorkspaces(groups.map((group) => group.work_dir)),
    [groups],
  );
  const normalizedDraftWorkDir = draftWorkDir.trim();
  const normalizedText = text.trim();
  const sessionBusy =
    runtime !== null &&
    (runtime.sessionState !== "idle" ||
      runtime.wsState === "connecting" ||
      runtime.wsState === "disconnected");
  const disableSubmit =
    submitting ||
    normalizedText.length === 0 ||
    (isDraft ? normalizedDraftWorkDir.length === 0 : sessionBusy);

  useEffect(() => {
    setText("");
  }, [activeSessionId]);

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
            <input
              id="draft-workspace"
              list="draft-workspace-options"
              value={draftWorkDir}
              onChange={(event) => {
                setDraftWorkDir(event.target.value);
              }}
              placeholder="/path/to/workspace"
              className="w-full rounded-xl border border-neutral-200 bg-white px-3 py-2 font-mono text-[13px] text-neutral-700 outline-none transition-colors placeholder:text-neutral-400 focus:border-neutral-400"
            />
            <datalist id="draft-workspace-options">
              {workspaceOptions.map((workspace) => (
                <option key={workspace} value={workspace} />
              ))}
            </datalist>
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
            rows={4}
            placeholder={isDraft ? "Message Klaude about this workspace..." : "Send a follow-up..."}
            className="max-h-64 min-h-[96px] w-full resize-y border-0 bg-transparent px-2 py-1 text-[14px] leading-6 text-neutral-800 outline-none placeholder:text-neutral-400"
          />

          <div className="mt-2 flex items-center justify-between gap-3 border-t border-neutral-100 px-2 pt-2">
            <div className="text-[11px] text-neutral-400">
              {isDraft
                ? normalizedDraftWorkDir.length > 0
                  ? normalizedDraftWorkDir
                  : "Pick a workspace before sending"
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
