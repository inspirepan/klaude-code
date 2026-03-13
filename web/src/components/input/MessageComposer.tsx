import { useCallback, useEffect, useRef, useState } from "react";

import { fetchConfigModels, type ConfigModelSummary } from "../../api/client";
import { useMessageStore } from "../../stores/message-store";
import { useSessionStore } from "../../stores/session-store";
import type {
  PendingUserInteractionRequest,
  UserInteractionResponse,
} from "../../types/interaction";
import { ComposerCard } from "./ComposerCard";
import { SessionStatusBar } from "./SessionStatusBar";
import { UserInteractionCard } from "./UserInteractionCard";

const EMPTY_PENDING_INTERACTIONS: PendingUserInteractionRequest[] = [];

export function MessageComposer(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const groups = useSessionStore((state) => state.groups);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const sendMessage = useSessionStore((state) => state.sendMessage);
  const interruptSession = useSessionStore((state) => state.interruptSession);
  const requestModel = useSessionStore((state) => state.requestModel);
  const respondInteraction = useSessionStore((state) => state.respondInteraction);
  const pendingInteractions = useSessionStore(
    (state) => state.pendingInteractionsBySessionId[activeSessionId] ?? EMPTY_PENDING_INTERACTIONS,
  );
  const statusBySessionId = useMessageStore(
    (state) => state.reducerStateBySessionId[activeSessionId]?.statusBySessionId ?? null,
  );
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modelOptions, setModelOptions] = useState<ConfigModelSummary[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [switchingModel, setSwitchingModel] = useState(false);
  const [pendingModelName, setPendingModelName] = useState<string | null>(null);
  const [respondingInteraction, setRespondingInteraction] = useState(false);
  const [interrupting, setInterrupting] = useState(false);
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
  const activeInteraction = pendingInteractions[0] ?? null;
  const sessionInterruptible =
    runtime?.sessionState === "running" ||
    (mainSessionStatus !== null &&
      !mainSessionStatus.awaitingInput &&
      (mainSessionStatus.taskActive ||
        mainSessionStatus.thinkingActive ||
        mainSessionStatus.compacting ||
        mainSessionStatus.isComposing));
  const disableSubmit =
    submitting ||
    normalizedText.length === 0 ||
    sessionBusy ||
    sessionReadOnly ||
    activeInteraction !== null;
  const currentModelName = pendingModelName ?? activeSession?.model_name ?? "";
  const modelBusy = sessionBusy || sessionReadOnly || modelLoading || switchingModel;
  const hasCurrentModelOption = modelOptions.some((option) => option.name === currentModelName);

  useEffect(() => {
    setText("");
    setPendingModelName(null);
    setModelError(null);
    setRespondingInteraction(false);
    setInterrupting(false);
  }, [activeSessionId]);

  useEffect(() => {
    if (!sessionInterruptible) {
      setInterrupting(false);
    }
  }, [sessionInterruptible]);

  useEffect(() => {
    if (activeInteraction === null) {
      setRespondingInteraction(false);
    }
  }, [activeInteraction]);

  useEffect(() => {
    let cancelled = false;
    setModelLoading(true);
    setModelError(null);
    void fetchConfigModels()
      .then((models) => {
        if (cancelled) {
          return;
        }
        setModelOptions(models);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        const message = error instanceof Error ? error.message : String(error);
        setModelError(message);
      })
      .finally(() => {
        if (cancelled) {
          return;
        }
        setModelLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (pendingModelName === null) {
      return;
    }
    if (activeSession?.model_name === pendingModelName) {
      setPendingModelName(null);
    }
  }, [activeSession?.model_name, pendingModelName]);

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

  const handleModelChange = useCallback(
    async (nextModelName: string) => {
      if (nextModelName.length === 0 || nextModelName === currentModelName || modelBusy) {
        return;
      }

      setModelError(null);
      setPendingModelName(nextModelName);
      setSwitchingModel(true);
      try {
        await requestModel(activeSessionId, nextModelName, false);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setPendingModelName(null);
        setModelError(message);
      } finally {
        setSwitchingModel(false);
      }
    },
    [activeSessionId, currentModelName, modelBusy, requestModel],
  );

  const handleInterrupt = useCallback(async () => {
    if (!sessionInterruptible || interrupting || sessionReadOnly) {
      return;
    }

    setInterrupting(true);
    try {
      await interruptSession(activeSessionId);
    } catch {
      setInterrupting(false);
    }
  }, [activeSessionId, interruptSession, interrupting, sessionInterruptible, sessionReadOnly]);

  useEffect(() => {
    if (!sessionInterruptible) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        event.isComposing ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      ) {
        return;
      }

      const target = event.target as HTMLElement | null;
      if (
        target !== null &&
        (target.tagName === "INPUT" ||
          target.tagName === "SELECT" ||
          target.isContentEditable ||
          (target.tagName === "TEXTAREA" && target !== textareaRef.current))
      ) {
        return;
      }

      event.preventDefault();
      void handleInterrupt();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleInterrupt, sessionInterruptible]);

  const resolvedModelOptions =
    hasCurrentModelOption || currentModelName.length === 0
      ? modelOptions
      : [
          {
            name: currentModelName,
            provider: "current",
            model_name: currentModelName,
            model_id: currentModelName,
            params: [],
            is_default: false,
          },
          ...modelOptions,
        ];

  return (
    <div className="relative shrink-0 px-4 pb-4 pt-10 sm:px-6">
      <div className="pointer-events-none absolute inset-0 z-0 bg-gradient-to-t from-white/95 via-white/80 to-transparent [-webkit-mask-image:linear-gradient(to_bottom,transparent,black_3rem)] [mask-image:linear-gradient(to_bottom,transparent,black_3rem)]" />
      <div className="relative z-10 mx-auto max-w-4xl space-y-3">
        <SessionStatusBar status={mainSessionStatus} runtime={runtime} />
        {activeInteraction ? (
          <UserInteractionCard
            request={activeInteraction}
            pendingCount={pendingInteractions.length}
            disabled={respondingInteraction}
            onRespond={async (response: UserInteractionResponse) => {
              setRespondingInteraction(true);
              try {
                await respondInteraction(activeSessionId, activeInteraction.requestId, response);
              } finally {
                setRespondingInteraction(false);
              }
            }}
          />
        ) : null}
        {modelError ? (
          <div className="px-1 text-xs text-red-500">Model switch failed: {modelError}</div>
        ) : null}
        <ComposerCard
          text={text}
          onTextChange={setText}
          onSubmit={() => {
            void handleSubmit();
          }}
          onInterrupt={() => {
            void handleInterrupt();
          }}
          submitting={submitting}
          disableSubmit={disableSubmit}
          interruptible={sessionInterruptible}
          disableInterrupt={interrupting || sessionReadOnly}
          placeholder="Send a follow-up..."
          modelOptions={resolvedModelOptions}
          modelValue={currentModelName}
          modelLoading={modelLoading}
          modelDisabled={modelBusy}
          onModelSelect={(modelName) => {
            void handleModelChange(modelName);
          }}
          textareaRef={textareaRef}
        />
      </div>
    </div>
  );
}
