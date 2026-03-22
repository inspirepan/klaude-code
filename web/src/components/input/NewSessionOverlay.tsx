import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useT } from "@/i18n";
import { useMountEffect } from "@/hooks/useMountEffect";
import { fetchConfigModels, listDirs, type ConfigModelSummary } from "../../api/client";
import { useSessionStore } from "../../stores/session-store";
import { ComposerCard, type ComposerImageAttachment } from "./ComposerCard";
import { DraftWorkspacePicker } from "./DraftWorkspacePicker";

interface NewSessionOverlayProps {
  onClose?: () => void;
  showBackdrop?: boolean;
}

function uniqueWorkspaces(workspaces: string[]): string[] {
  return [...new Set(workspaces.filter((item) => item.trim().length > 0))];
}

export function NewSessionOverlay({
  onClose,
  showBackdrop = true,
}: NewSessionOverlayProps): JSX.Element {
  const t = useT();
  const draftWorkDir = useSessionStore((state) => state.draftWorkDir);
  const groups = useSessionStore((state) => state.groups);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const createSessionFromDraft = useSessionStore((state) => state.createSessionFromDraft);

  const [text, setText] = useState("");
  const [images, setImages] = useState<ComposerImageAttachment[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(
    () => draftWorkDir.trim().length === 0,
  );
  const [modelOptions, setModelOptions] = useState<ConfigModelSummary[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const workspacePickerRef = useRef<HTMLDivElement>(null);
  const workspaceInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const initialDraftWorkDirRef = useRef(draftWorkDir);

  const workspaceOptions = useMemo(
    () => uniqueWorkspaces(groups.map((group) => group.work_dir)),
    [groups],
  );
  const normalizedDraftWorkDir = draftWorkDir.trim();
  const [dirCompletions, setDirCompletions] = useState<string[]>([]);
  const filteredWorkspaceOptions = useMemo(() => {
    if (normalizedDraftWorkDir.length === 0) {
      return workspaceOptions;
    }
    const query = normalizedDraftWorkDir.toLowerCase();
    const historyMatches = workspaceOptions.filter((workspace) =>
      workspace.toLowerCase().includes(query),
    );
    // Merge filesystem completions, deduplicating against history matches
    const seen = new Set(historyMatches.map((w) => w.replace(/\/+$/, "")));
    const fsMatches = dirCompletions.filter((dir) => !seen.has(dir.replace(/\/+$/, "")));
    return [...historyMatches, ...fsMatches];
  }, [normalizedDraftWorkDir, workspaceOptions, dirCompletions]);

  useEffect(() => {
    if (normalizedDraftWorkDir.length === 0) {
      setDirCompletions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void listDirs(normalizedDraftWorkDir, controller.signal)
        .then((items) => {
          if (!controller.signal.aborted) {
            setDirCompletions(items);
          }
        })
        .catch(() => {
          // ignore aborted / network errors
        });
    }, 150);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [normalizedDraftWorkDir]);

  const normalizedText = text.trim();
  const hasImages = images.length > 0;
  const disableSubmit =
    submitting ||
    (normalizedText.length === 0 && !hasImages) ||
    normalizedDraftWorkDir.length === 0;

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
        const defaultModel = models.find((item) => item.is_default)?.name ?? models[0]?.name ?? "";
        setSelectedModel(defaultModel);
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
  });

  useMountEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (initialDraftWorkDirRef.current.trim().length === 0) {
        workspaceInputRef.current?.focus();
      } else {
        textareaRef.current?.focus();
      }
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  });

  useMountEffect(() => {
    const handleDraftFocusRequest = () => {
      textareaRef.current?.focus();
    };
    window.addEventListener("klaude:draft-focus-input", handleDraftFocusRequest);
    return () => {
      window.removeEventListener("klaude:draft-focus-input", handleDraftFocusRequest);
    };
  });

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      if (workspaceMenuOpen) {
        setWorkspaceMenuOpen(false);
        return;
      }
      onClose?.();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, workspaceMenuOpen]);

  useMountEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!workspacePickerRef.current?.contains(event.target as Node)) {
        setWorkspaceMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  });

  const handleSubmit = useCallback(async () => {
    if (disableSubmit) {
      return;
    }

    setSubmitting(true);
    try {
      await createSessionFromDraft(
        normalizedText,
        normalizedDraftWorkDir,
        selectedModel,
        images.map((attachment) => attachment.image),
      );
      setText("");
      setImages([]);
      onClose?.();
    } finally {
      setSubmitting(false);
    }
  }, [
    createSessionFromDraft,
    disableSubmit,
    normalizedDraftWorkDir,
    images,
    normalizedText,
    onClose,
    selectedModel,
  ]);

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center px-4 py-6 sm:px-6">
      {showBackdrop ? (
        <div
          className="bg-card/72 absolute inset-0 backdrop-blur-[3px]"
          onClick={() => {
            onClose?.();
          }}
        />
      ) : null}
      <div
        className={`relative w-full max-w-2xl -translate-y-[25vh] rounded-xl border border-border/90 bg-card p-3 ${
          showBackdrop ? "shadow-overlay" : ""
        } sm:p-4`}
      >
        <div className="mb-3 space-y-0.5">
          <div className="text-base font-semibold text-neutral-800">{t("newSession.title")}</div>
          <div className="text-base leading-6 text-neutral-500">{t("newSession.subtitle")}</div>
        </div>

        <div className="space-y-3">
          <DraftWorkspacePicker
            draftWorkDir={draftWorkDir}
            normalizedDraftWorkDir={normalizedDraftWorkDir}
            workspaceMenuOpen={workspaceMenuOpen}
            filteredWorkspaceOptions={filteredWorkspaceOptions}
            workspacePickerRef={workspacePickerRef}
            inputRef={workspaceInputRef}
            setDraftWorkDir={setDraftWorkDir}
            setWorkspaceMenuOpen={setWorkspaceMenuOpen}
            onSelect={() => {
              window.requestAnimationFrame(() => {
                textareaRef.current?.focus();
              });
            }}
          />

          {normalizedDraftWorkDir.length > 0 ? (
            <>
              {modelError ? (
                <div className="px-1 text-sm text-red-500">
                  {t("newSession.loadModelsFailed")(modelError)}
                </div>
              ) : null}

              <ComposerCard
                sessionId=""
                searchWorkDir={normalizedDraftWorkDir}
                skillWorkDir={normalizedDraftWorkDir}
                text={text}
                onTextChange={setText}
                images={images}
                onImagesChange={setImages}
                onSubmit={() => {
                  void handleSubmit();
                }}
                submitting={submitting}
                disableSubmit={disableSubmit}
                disableAttachments={submitting}
                placeholder={t("composer.draftPlaceholder")}
                modelOptions={modelOptions}
                modelValue={selectedModel}
                modelLoading={modelLoading}
                modelDisabled={submitting || modelOptions.length === 0}
                modelPlaceholder={t("model.defaultModel")}
                onModelSelect={setSelectedModel}
                modelDropUp={false}
                completionDropUp={false}
                textareaRef={textareaRef}
              />
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
