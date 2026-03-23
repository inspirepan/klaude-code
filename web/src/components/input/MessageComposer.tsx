import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "@/i18n";
import { useMountEffect } from "@/hooks/useMountEffect";
import { fetchConfigModels, type ConfigModelSummary } from "../../api/client";
import { useMessageStore } from "../../stores/message-store";
import { useSessionStore } from "../../stores/session-store";
import type {
  PendingUserInteractionRequest,
  UserInteractionResponse,
} from "../../types/interaction";
import { ComposerCard, type ComposerImageAttachment } from "./ComposerCard";
import { UserInteractionCard } from "./UserInteractionCard";

const EMPTY_PENDING_INTERACTIONS: PendingUserInteractionRequest[] = [];

export function MessageComposer(): JSX.Element {
  const t = useT();
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const groups = useSessionStore((state) => state.groups);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const sendMessage = useSessionStore((state) => state.sendMessage);
  const compactSession = useSessionStore((state) => state.compactSession);
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
  const [images, setImages] = useState<ComposerImageAttachment[]>([]);
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
  const hasImages = images.length > 0;
  const sessionBusy =
    runtime !== null &&
    (runtime.sessionState !== "idle" ||
      runtime.wsState === "connecting" ||
      runtime.wsState === "disconnected");
  const sessionReadOnly = activeSession?.read_only === true;
  const mainSessionStatus = statusBySessionId?.[activeSessionId] ?? null;
  const activeInteraction = pendingInteractions.at(0) ?? null;
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
    (normalizedText.length === 0 && !hasImages) ||
    sessionBusy ||
    sessionReadOnly ||
    activeInteraction !== null;
  const effectivePendingModelName =
    pendingModelName !== null && pendingModelName !== activeSession?.model_name
      ? pendingModelName
      : null;
  const currentModelName = effectivePendingModelName ?? activeSession?.model_name ?? "";
  const effectiveRespondingInteraction = respondingInteraction && activeInteraction !== null;
  const modelBusy = sessionBusy || sessionReadOnly || modelLoading || switchingModel;
  const hasCurrentModelOption = modelOptions.some((option) => option.name === currentModelName);

  // Reset interrupting when session is no longer interruptible (e.g. finished).
  // Cannot be derived: the underlying `interrupting` state must be cleared so it
  // does not re-activate when the next run makes `sessionInterruptible` true again.
  useEffect(() => {
    if (!sessionInterruptible) {
      setInterrupting(false);
    }
  }, [sessionInterruptible]);

  useMountEffect(() => {
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
      .catch((error: unknown) => {
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
  });

  const handleSubmit = useCallback(async () => {
    if (disableSubmit) {
      return;
    }

    setSubmitting(true);
    try {
      await sendMessage(
        activeSessionId,
        normalizedText,
        images.map((attachment) => attachment.image),
      );
      setText("");
      setImages([]);
    } finally {
      setSubmitting(false);
    }
  }, [activeSessionId, disableSubmit, images, normalizedText, sendMessage]);

  const handleCompact = useCallback(
    async (focus: string | null) => {
      await compactSession(activeSessionId, focus);
      setText("");
    },
    [activeSessionId, compactSession],
  );

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
  }, [activeSessionId, interrupting, interruptSession, sessionInterruptible, sessionReadOnly]);

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
    <div className="relative shrink-0 overflow-visible px-4 pb-4 sm:px-6">
      <div className="pointer-events-none absolute -top-12 bottom-0 left-0 right-0 z-0 bg-gradient-to-t from-white/95 via-white/80 via-[30%] to-transparent [backface-visibility:hidden]" />
      <div className="relative z-10 mx-auto max-w-4xl space-y-3">
        {activeInteraction ? (
          <UserInteractionCard
            key={activeInteraction.requestId}
            request={activeInteraction}
            pendingCount={pendingInteractions.length}
            disabled={effectiveRespondingInteraction}
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
          <div className="px-1 text-sm text-red-500">
            {t("newSession.modelSwitchFailed")(modelError)}
          </div>
        ) : null}
        <ComposerCard
          sessionId={activeSessionId}
          skillWorkDir={activeSession?.work_dir}
          text={text}
          onTextChange={setText}
          images={images}
          onImagesChange={setImages}
          onSubmit={() => {
            void handleSubmit();
          }}
          onCompact={(focus) => {
            void handleCompact(focus);
          }}
          onInterrupt={() => {
            void handleInterrupt();
          }}
          submitting={submitting}
          disableSubmit={disableSubmit}
          interruptible={sessionInterruptible}
          disableInterrupt={interrupting || sessionReadOnly}
          disableAttachments={
            sessionBusy || sessionReadOnly || activeInteraction !== null || submitting
          }
          placeholder={t("composer.followUpPlaceholder")}
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
