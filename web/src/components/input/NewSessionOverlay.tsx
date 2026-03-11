import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SendHorizonal } from "lucide-react";

import { fetchConfigModels, type ConfigModelSummary } from "../../api/client";
import { useSessionStore } from "../../stores/session-store";
import { DraftWorkspacePicker } from "./DraftWorkspacePicker";
import { ModelSelector } from "./ModelSelector";

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
  const draftWorkDir = useSessionStore((state) => state.draftWorkDir);
  const groups = useSessionStore((state) => state.groups);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const createSessionFromDraft = useSessionStore((state) => state.createSessionFromDraft);

  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState<ConfigModelSummary[]>([]);
  const [modelLoading, setModelLoading] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const workspacePickerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
  const disableSubmit =
    submitting || normalizedText.length === 0 || normalizedDraftWorkDir.length === 0;

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
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    const handleDraftFocusRequest = () => {
      textareaRef.current?.focus();
    };
    window.addEventListener("klaude:draft-focus-input", handleDraftFocusRequest);
    return () => {
      window.removeEventListener("klaude:draft-focus-input", handleDraftFocusRequest);
    };
  }, []);

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

  useEffect(() => {
    resizeTextarea();
  }, [resizeTextarea, text]);

  const handleSubmit = useCallback(async () => {
    if (disableSubmit) {
      return;
    }

    setSubmitting(true);
    try {
      await createSessionFromDraft(normalizedText, normalizedDraftWorkDir, selectedModel);
      setText("");
      onClose?.();
    } finally {
      setSubmitting(false);
    }
  }, [
    createSessionFromDraft,
    disableSubmit,
    normalizedDraftWorkDir,
    normalizedText,
    onClose,
    selectedModel,
  ]);

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center px-4 py-6 sm:px-6">
      {showBackdrop ? (
        <div
          className="bg-white/72 absolute inset-0 backdrop-blur-[3px]"
          onClick={() => {
            onClose?.();
          }}
        />
      ) : null}
      <div
        className={`relative w-full max-w-2xl -translate-y-[25vh] rounded-3xl border border-neutral-200/90 bg-white p-4 ${
          showBackdrop ? "shadow-[0_24px_80px_rgba(0,0,0,0.14)]" : ""
        } sm:p-6`}
      >
        <div className="mb-4 space-y-1">
          <div className="text-base font-semibold text-neutral-800">Start a new session</div>
          <div className="text-sm leading-6 text-neutral-500">
            Choose a workspace, then send your first message.
          </div>
        </div>

        <div className="space-y-3">
          <DraftWorkspacePicker
            draftWorkDir={draftWorkDir}
            normalizedDraftWorkDir={normalizedDraftWorkDir}
            workspaceMenuOpen={workspaceMenuOpen}
            filteredWorkspaceOptions={filteredWorkspaceOptions}
            workspacePickerRef={workspacePickerRef}
            setDraftWorkDir={setDraftWorkDir}
            setWorkspaceMenuOpen={setWorkspaceMenuOpen}
          />

          {modelError ? (
            <div className="px-1 text-xs text-red-500">Load models failed: {modelError}</div>
          ) : null}

          <div className="rounded-[30px] bg-white px-4 py-3 shadow-sm ring-1 ring-black/5">
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
              placeholder="What should we do?"
              className="min-h-12 w-full resize-none overflow-y-hidden border-0 bg-transparent px-0 py-0.5 text-[15px] leading-7 text-neutral-800 outline-none placeholder:text-neutral-400"
            />
            <div className="mt-2 flex items-center justify-between gap-2">
              <ModelSelector
                options={modelOptions}
                value={selectedModel}
                loading={modelLoading}
                disabled={submitting || modelOptions.length === 0}
                placeholder="Default model"
                onSelect={setSelectedModel}
                triggerClassName="inline-flex h-10 items-center gap-1.5 rounded-xl bg-neutral-100 px-4 text-[13px] text-neutral-700 transition-colors hover:bg-neutral-200 disabled:cursor-not-allowed disabled:text-neutral-400"
                panelClassName="absolute bottom-full left-0 z-30 mb-2 w-[360px] overflow-hidden rounded-xl border border-neutral-200 bg-white/95 p-1.5 shadow-[0_16px_40px_rgba(0,0,0,0.12)] backdrop-blur"
              />
              <button
                type="button"
                onClick={() => {
                  void handleSubmit();
                }}
                disabled={disableSubmit}
                aria-label={submitting ? "Sending" : "Send"}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-neutral-900 text-white transition-colors hover:bg-neutral-800 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
              >
                <SendHorizonal className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
