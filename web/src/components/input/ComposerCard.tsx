import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { ArrowUp, Plus, Square, X } from "lucide-react";

import { buildFileApiUrl, uploadImageAttachment, type ConfigModelSummary } from "../../api/client";
import type { MessageImageFilePart } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { AtFileCompletionList } from "./AtFileCompletionList";
import { ModelSelector } from "./ModelSelector";
import { SlashCompletionList } from "./SlashCompletionList";
import { useFileCompletion } from "./useFileCompletion";
import { useSlashCompletion } from "./useSlashCompletion";

const SUPPORTED_IMAGE_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const SUPPORTED_IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
const COMPACT_COMMAND_PATTERN = /^\/compact(?:\s+(?<focus>.+))?$/;

export interface ComposerImageAttachment {
  id: string;
  name: string;
  image: MessageImageFilePart;
}

interface ComposerSubmitPayload {
  text: string;
  images: MessageImageFilePart[];
}

interface ComposerCardProps {
  sessionId: string;
  searchWorkDir?: string;
  /** Working directory used for skill discovery. When provided, skills are
   *  re-fetched whenever this value changes (e.g. workspace switch). */
  skillWorkDir?: string;
  text: string;
  onTextChange: (text: string) => void;
  images: ComposerImageAttachment[];
  onImagesChange: Dispatch<SetStateAction<ComposerImageAttachment[]>>;
  onSubmit: (payload: ComposerSubmitPayload) => void;
  onCompact?: (focus: string | null) => void;
  onInterrupt?: () => void;
  submitting: boolean;
  disableSubmit: boolean;
  interruptible?: boolean;
  disableInterrupt?: boolean;
  disableAttachments?: boolean;
  disableInput?: boolean;
  placeholder?: string;
  modelOptions: ConfigModelSummary[];
  modelValue: string;
  modelLoading?: boolean;
  modelDisabled?: boolean;
  modelPlaceholder?: string;
  onModelSelect: (modelName: string) => void;
  textareaRef?: RefObject<HTMLTextAreaElement>;
  /** Open model dropdown above (default) or below the trigger. */
  modelDropUp?: boolean;
  /** Open completion lists above (default) or below the textarea. */
  completionDropUp?: boolean;
}

function parseCompactCommand(text: string): { focus: string | null } | null {
  const match = COMPACT_COMMAND_PATTERN.exec(text.trim());
  if (!match) return null;
  return { focus: match.groups?.focus?.trim() || null };
}

function getAttachmentName(file: File, image: MessageImageFilePart): string {
  const trimmedName = file.name.trim();
  if (trimmedName.length > 0) {
    return trimmedName;
  }
  const filename = image.file_path.split("/").at(-1)?.trim();
  if (filename && filename.length > 0) {
    return filename;
  }
  return "image";
}

export function ComposerCard({
  sessionId,
  searchWorkDir,
  skillWorkDir,
  text,
  onTextChange,
  images,
  onImagesChange,
  onSubmit,
  onCompact,
  onInterrupt,
  submitting,
  disableSubmit,
  interruptible = false,
  disableInterrupt = false,
  disableAttachments = false,
  disableInput = false,
  placeholder = "Send a message...",
  modelOptions,
  modelValue,
  modelLoading = false,
  modelDisabled = false,
  modelPlaceholder,
  onModelSelect,
  textareaRef: externalRef,
  modelDropUp = true,
  completionDropUp = true,
}: ComposerCardProps): JSX.Element {
  const internalRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const ref = externalRef ?? internalRef;
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadingCount, setUploadingCount] = useState(0);

  const fileComp = useFileCompletion({
    sessionId,
    searchWorkDir,
    text,
    onTextChange,
    textareaRef: ref,
  });

  const slashComp = useSlashCompletion({
    skillWorkDir,
    hasCompact: !!onCompact,
    onTextChange,
    textareaRef: ref,
  });

  const attachmentsDisabled = disableAttachments || interruptible || uploadingCount > 0;
  const buttonDisabled = uploadingCount > 0 || (interruptible ? disableInterrupt : disableSubmit);
  const buttonLabel = interruptible ? "Interrupt" : submitting ? "Sending" : "Send";
  const anyCompletionOpen = fileComp.open || slashComp.open;

  const handleSubmitOrCompact = useCallback(() => {
    const compact = parseCompactCommand(text);
    if (compact && onCompact) {
      onCompact(compact.focus);
      return;
    }
    onSubmit({ text, images: images.map((item) => item.image) });
  }, [images, onCompact, onSubmit, text]);

  useEffect(() => {
    const textarea = ref.current;
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
    const maxHeight = singleLineHeight * 10;

    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [ref, text]);

  useEffect(() => {
    if (!anyCompletionOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        fileComp.close();
        slashComp.close();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [anyCompletionOpen, fileComp, slashComp]);

  useEffect(() => {
    if (text.length === 0) {
      fileComp.close();
      slashComp.close();
    }
  }, [fileComp, slashComp, text]);

  const handleFileBatch = async (files: File[]): Promise<void> => {
    if (files.length === 0) {
      return;
    }

    if (files.some((file) => !SUPPORTED_IMAGE_MIME_TYPES.has(file.type))) {
      setUploadError("Only PNG, JPEG, GIF, and WebP images are supported.");
      return;
    }

    setUploadError(null);
    setUploadingCount((current) => current + files.length);
    try {
      const uploaded = await Promise.all(
        files.map(async (file) => {
          const image = await uploadImageAttachment(file);
          return {
            id: crypto.randomUUID(),
            name: getAttachmentName(file, image),
            image,
          } satisfies ComposerImageAttachment;
        }),
      );
      onImagesChange((current) => [...current, ...uploaded]);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setUploadError(message);
    } finally {
      setUploadingCount((current) => Math.max(0, current - files.length));
      ref.current?.focus();
    }
  };

  return (
    <div
      ref={rootRef}
      className="rounded-lg bg-white px-4 py-2.5 shadow-sm ring-1 ring-black/[0.06]"
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={SUPPORTED_IMAGE_ACCEPT}
        multiple
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          void handleFileBatch(files);
          event.target.value = "";
        }}
      />
      <div className="relative">
        <textarea
          ref={ref}
          value={text}
          onChange={(event) => {
            onTextChange(event.target.value);
            fileComp.update(event.target.value, event.target.selectionStart);
            slashComp.update(event.target.value, event.target.selectionStart);
          }}
          onSelect={(event) => {
            fileComp.update(event.currentTarget.value, event.currentTarget.selectionStart);
            slashComp.update(event.currentTarget.value, event.currentTarget.selectionStart);
          }}
          onPaste={(event) => {
            const files = Array.from(event.clipboardData.items)
              .filter((item) => item.kind === "file")
              .map((item) => item.getAsFile())
              .filter((file): file is File => file !== null);
            if (files.length === 0) {
              return;
            }
            event.preventDefault();
            void handleFileBatch(files);
          }}
          onKeyDown={(event) => {
            if (fileComp.open) {
              if (event.key === "ArrowDown" && fileComp.items.length > 0) {
                event.preventDefault();
                fileComp.setHighlightIndex(
                  Math.min(fileComp.highlightIndex + 1, fileComp.items.length - 1),
                );
                return;
              }
              if (event.key === "ArrowUp" && fileComp.items.length > 0) {
                event.preventDefault();
                fileComp.setHighlightIndex(Math.max(fileComp.highlightIndex - 1, 0));
                return;
              }
              if ((event.key === "Enter" || event.key === "Tab") && fileComp.items.length > 0) {
                event.preventDefault();
                const path = fileComp.items[fileComp.highlightIndex];
                if (path) {
                  fileComp.apply(path);
                }
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                fileComp.close();
                return;
              }
            }

            if (slashComp.open) {
              if (event.key === "ArrowDown" && slashComp.items.length > 0) {
                event.preventDefault();
                slashComp.setHighlightIndex(
                  Math.min(slashComp.highlightIndex + 1, slashComp.items.length - 1),
                );
                return;
              }
              if (event.key === "ArrowUp" && slashComp.items.length > 0) {
                event.preventDefault();
                slashComp.setHighlightIndex(Math.max(slashComp.highlightIndex - 1, 0));
                return;
              }
              if ((event.key === "Enter" || event.key === "Tab") && slashComp.items.length > 0) {
                event.preventDefault();
                const item = slashComp.items[slashComp.highlightIndex];
                if (item) {
                  slashComp.apply(item);
                }
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                slashComp.close();
                return;
              }
            }

            if (event.nativeEvent.isComposing || event.key !== "Enter" || event.shiftKey) {
              return;
            }
            event.preventDefault();
            if (buttonDisabled) {
              return;
            }
            handleSubmitOrCompact();
          }}
          rows={1}
          disabled={disableInput}
          placeholder={placeholder}
          className="min-h-[2rem] w-full resize-none overflow-y-hidden border-0 bg-transparent px-0 py-0.5 text-base leading-7 text-neutral-800 outline-none placeholder:text-neutral-400 disabled:cursor-not-allowed disabled:opacity-40"
        />
        {fileComp.open ? (
          <AtFileCompletionList
            items={fileComp.items}
            loading={fileComp.loading}
            highlightIndex={fileComp.highlightIndex}
            onHighlightIndexChange={fileComp.setHighlightIndex}
            onSelect={fileComp.apply}
            dropUp={completionDropUp}
          />
        ) : null}
        {slashComp.open ? (
          <SlashCompletionList
            items={slashComp.items}
            highlightIndex={slashComp.highlightIndex}
            onHighlightIndexChange={slashComp.setHighlightIndex}
            onSelect={slashComp.apply}
            dropUp={completionDropUp}
          />
        ) : null}
      </div>
      {images.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {images.map((attachment) => (
            <div
              key={attachment.id}
              className="group relative overflow-hidden rounded-md border border-neutral-200/80 bg-surface"
            >
              <img
                src={buildFileApiUrl(attachment.image.file_path)}
                alt={attachment.name}
                className="block h-16 w-16 object-cover"
              />
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={() => {
                      onImagesChange((current) =>
                        current.filter((item) => item.id !== attachment.id),
                      );
                    }}
                    className="absolute right-1 top-1 inline-flex h-5 w-5 items-center justify-center rounded-full bg-black/70 text-white opacity-0 transition-opacity group-hover:opacity-100"
                    aria-label="Remove image"
                  >
                    <X className="h-3 w-3" strokeWidth={2.5} />
                  </button>
                </TooltipTrigger>
                <TooltipContent>Remove image</TooltipContent>
              </Tooltip>
            </div>
          ))}
        </div>
      ) : null}
      {uploadingCount > 0 ? (
        <div className="mt-2 text-sm text-neutral-500">
          Uploading {uploadingCount === 1 ? "image" : `${uploadingCount} images`}...
        </div>
      ) : null}
      {uploadError ? <div className="mt-2 text-sm text-red-500">{uploadError}</div> : null}
      <div className="mt-1 flex items-center justify-between gap-3">
        <ModelSelector
          options={modelOptions}
          value={modelValue}
          loading={modelLoading}
          disabled={modelDisabled}
          placeholder={modelPlaceholder}
          onSelect={(modelName) => {
            onModelSelect(modelName);
            requestAnimationFrame(() => ref.current?.focus());
          }}
          dropUp={modelDropUp}
        />
        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => {
                  fileInputRef.current?.click();
                }}
                disabled={attachmentsDisabled}
                aria-label="Add image"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-neutral-200 bg-white text-neutral-500 transition-colors hover:border-neutral-300 hover:text-neutral-700 disabled:cursor-not-allowed disabled:border-neutral-200 disabled:text-neutral-300"
              >
                <Plus className="h-4 w-4" strokeWidth={2.2} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Add image or paste from clipboard</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={interruptible ? onInterrupt : handleSubmitOrCompact}
                disabled={buttonDisabled}
                aria-label={buttonLabel}
                className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white transition-colors disabled:cursor-not-allowed ${
                  interruptible
                    ? "bg-amber-600 hover:bg-amber-500 disabled:bg-amber-200 disabled:text-amber-50"
                    : "bg-neutral-800 hover:bg-neutral-700 disabled:bg-neutral-100 disabled:text-neutral-300"
                }`}
              >
                {interruptible ? (
                  <Square className="h-3.5 w-3.5 fill-current" strokeWidth={2.5} />
                ) : (
                  <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent className="flex items-center gap-1.5">
              <span>{buttonLabel}</span>
              {interruptible ? (
                <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
                  <span className="inline-flex whitespace-pre text-[12px] leading-none">
                    <kbd className="inline-flex font-sans">
                      <span className="min-w-[1em] text-center">Esc</span>
                    </kbd>
                  </span>
                </span>
              ) : null}
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}
