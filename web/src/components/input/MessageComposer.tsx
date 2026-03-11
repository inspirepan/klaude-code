import { useCallback, useEffect, useRef, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { useMessageStore } from "../../stores/message-store";
import { useSessionStore } from "../../stores/session-store";
import { SessionStatusBar } from "./SessionStatusBar";

export function MessageComposer(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const groups = useSessionStore((state) => state.groups);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const sendMessage = useSessionStore((state) => state.sendMessage);
  const statusBySessionId = useMessageStore(
    (state) => state.reducerStateBySessionId[activeSessionId]?.statusBySessionId ?? null,
  );
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const runtime = runtimeBySessionId[activeSessionId] ?? null;
  const activeSession =
    groups.flatMap((group) => group.sessions).find((session) => session.id === activeSessionId) ??
    null;
  const normalizedText = text.trim();
  const sessionBusy =
    runtime !== null &&
    (runtime.sessionState !== "idle" ||
      runtime.wsState === "connecting" ||
      runtime.wsState === "disconnected");
  const sessionReadOnly = activeSession?.read_only === true;
  const mainSessionStatus = statusBySessionId?.[activeSessionId] ?? null;
  const disableSubmit = submitting || normalizedText.length === 0 || sessionBusy || sessionReadOnly;

  const resizeTextarea = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }

    const styles = window.getComputedStyle(textarea);
    const lineHeight = Number.parseFloat(styles.lineHeight);
    const paddingTop = Number.parseFloat(styles.paddingTop);
    const paddingBottom = Number.parseFloat(styles.paddingBottom);
    const borderTopWidth = Number.parseFloat(styles.borderTopWidth);
    const borderBottomWidth = Number.parseFloat(styles.borderBottomWidth);

    const singleLineHeight =
      lineHeight + paddingTop + paddingBottom + borderTopWidth + borderBottomWidth;
    const maxHeight = singleLineHeight * 2;

    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, []);

  useEffect(() => {
    setText("");
  }, [activeSessionId]);

  useEffect(() => {
    resizeTextarea();
  }, [resizeTextarea, text]);

  const handleSubmit = useCallback(async () => {
    if (disableSubmit) {
      return;
    }

    setSubmitting(true);
    try {
      await sendMessage(activeSessionId, normalizedText);
      setText("");
    } finally {
      setSubmitting(false);
    }
  }, [activeSessionId, disableSubmit, normalizedText, sendMessage]);

  return (
    <div className="relative shrink-0 px-4 pb-4 pt-10 sm:px-6">
      <div className="pointer-events-none absolute inset-0 z-0 bg-gradient-to-t from-white/95 via-white/80 to-transparent [-webkit-mask-image:linear-gradient(to_bottom,transparent,black_3rem)] [mask-image:linear-gradient(to_bottom,transparent,black_3rem)]" />
      <div className="relative z-10 mx-auto max-w-4xl space-y-3">
        <SessionStatusBar status={mainSessionStatus} runtime={runtime} />
        <div className="flex items-end gap-2 rounded-full bg-white p-3 shadow-sm ring-1 ring-black/5">
          <textarea
            ref={textareaRef}
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
            rows={1}
            placeholder="Send a follow-up..."
            className="min-h-7 flex-1 resize-none overflow-y-hidden border-0 bg-transparent px-1 py-0.5 text-sm leading-6 text-neutral-800 outline-none placeholder:text-neutral-400"
          />
          <button
            type="button"
            onClick={() => {
              void handleSubmit();
            }}
            disabled={disableSubmit}
            aria-label={submitting ? "Sending" : "Send"}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-white transition-colors hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
          >
            <SendHorizonal className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
