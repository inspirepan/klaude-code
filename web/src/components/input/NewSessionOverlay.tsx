import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, SendHorizonal } from "lucide-react";

import { fetchConfigModels } from "../../api/client";
import { useSessionStore } from "../../stores/session-store";
import { DraftWorkspacePicker } from "./DraftWorkspacePicker";

interface NewSessionOverlayProps {
  onClose?: () => void;
  showBackdrop?: boolean;
}

interface ModelOption {
  name: string;
  is_default: boolean;
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
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
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

          <div className="flex items-end gap-2 rounded-[22px] bg-white p-3 shadow-sm ring-1 ring-black/5">
            <div className="relative shrink-0">
              <select
                value={selectedModel}
                disabled={modelLoading || modelOptions.length === 0 || submitting}
                onChange={(event) => {
                  setSelectedModel(event.target.value);
                }}
                className="h-7 max-w-48 appearance-none rounded-full border border-neutral-200 bg-neutral-50 pl-3 pr-7 text-xs text-neutral-700 outline-none transition-colors focus:border-neutral-300 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-neutral-400"
              >
                {selectedModel.length === 0 ? (
                  <option value="" disabled>
                    {modelLoading ? "Loading models..." : "Default model"}
                  </option>
                ) : null}
                {modelOptions.map((option) => (
                  <option key={option.name} value={option.name}>
                    {option.is_default ? `${option.name} (default)` : option.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-neutral-400" />
            </div>
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
    </div>
  );
}
