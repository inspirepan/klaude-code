import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { ArrowUp, ImagePlus, Square, X } from "lucide-react";

import {
  buildFileApiUrl,
  searchFileCompletions,
  uploadImageAttachment,
  type ConfigModelSummary,
} from "../../api/client";
import type { MessageImageFilePart } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { AtFileCompletionList } from "./AtFileCompletionList";
import { ModelSelector } from "./ModelSelector";

const SUPPORTED_IMAGE_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const SUPPORTED_IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";
const AT_COMPLETION_PATTERN = /(^|\s)@(?<frag>"[^"]*"|[^\s]*)$/;
const AT_COMPLETION_DEBOUNCE_MS = 120;

interface FileCompletionContext {
  fragment: string;
  searchQuery: string;
  tokenStart: number;
  tokenEnd: number;
  isQuoted: boolean;
}

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
  text: string;
  onTextChange: (text: string) => void;
  images: ComposerImageAttachment[];
  onImagesChange: Dispatch<SetStateAction<ComposerImageAttachment[]>>;
  onSubmit: (payload: ComposerSubmitPayload) => void;
  onInterrupt?: () => void;
  submitting: boolean;
  disableSubmit: boolean;
  interruptible?: boolean;
  disableInterrupt?: boolean;
  disableAttachments?: boolean;
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
}

function getFileCompletionContext(
  text: string,
  cursorPosition: number,
): FileCompletionContext | null {
  const textBeforeCursor = text.slice(0, cursorPosition);
  const match = AT_COMPLETION_PATTERN.exec(textBeforeCursor);
  const fragment = match?.groups?.frag;
  if (fragment === undefined) {
    return null;
  }

  let searchQuery = fragment;
  const isQuoted = fragment.startsWith('"');
  if (isQuoted) {
    searchQuery = searchQuery.slice(1);
    if (searchQuery.endsWith('"')) {
      searchQuery = searchQuery.slice(0, -1);
    }
  }

  return {
    fragment,
    searchQuery,
    tokenStart: textBeforeCursor.length - `@${fragment}`.length,
    tokenEnd: cursorPosition,
    isQuoted,
  };
}

function formatFileCompletionText(path: string, isQuoted: boolean): string {
  if (isQuoted || /\s/.test(path)) {
    return `@"${path}" `;
  }
  return `@${path} `;
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
  text,
  onTextChange,
  images,
  onImagesChange,
  onSubmit,
  onInterrupt,
  submitting,
  disableSubmit,
  interruptible = false,
  disableInterrupt = false,
  disableAttachments = false,
  placeholder = "Send a message...",
  modelOptions,
  modelValue,
  modelLoading = false,
  modelDisabled = false,
  modelPlaceholder,
  onModelSelect,
  textareaRef: externalRef,
  modelDropUp = true,
}: ComposerCardProps): JSX.Element {
  const internalRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const ref = externalRef ?? internalRef;
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [fileCompletion, setFileCompletion] = useState<FileCompletionContext | null>(null);
  const [fileCompletionItems, setFileCompletionItems] = useState<string[]>([]);
  const [fileCompletionLoading, setFileCompletionLoading] = useState(false);
  const [fileCompletionHighlightIndex, setFileCompletionHighlightIndex] = useState(0);
  const attachmentsDisabled = disableAttachments || interruptible || uploadingCount > 0;
  const buttonDisabled = uploadingCount > 0 || (interruptible ? disableInterrupt : disableSubmit);
  const buttonLabel = interruptible ? "Interrupt" : submitting ? "Sending" : "Send";
  const fileCompletionOpen = fileCompletionLoading || fileCompletionItems.length > 0;

  const closeFileCompletion = useCallback(() => {
    setFileCompletion(null);
    setFileCompletionItems([]);
    setFileCompletionLoading(false);
    setFileCompletionHighlightIndex(0);
  }, []);

  const updateFileCompletion = useCallback((nextText: string, cursorPosition: number | null) => {
    const resolvedCursor = cursorPosition ?? nextText.length;
    const nextCompletion = getFileCompletionContext(nextText, resolvedCursor);
    setFileCompletion((current) => {
      if (
        current?.fragment === nextCompletion?.fragment &&
        current?.tokenStart === nextCompletion?.tokenStart &&
        current?.tokenEnd === nextCompletion?.tokenEnd
      ) {
        return current;
      }
      return nextCompletion;
    });
    if (nextCompletion === null) {
      setFileCompletionItems([]);
      setFileCompletionLoading(false);
    }
    setFileCompletionHighlightIndex(0);
  }, []);

  const applyFileCompletion = useCallback(
    (path: string) => {
      if (fileCompletion === null) {
        return;
      }

      const insertedText = formatFileCompletionText(path, fileCompletion.isQuoted);
      const nextText = `${text.slice(0, fileCompletion.tokenStart)}${insertedText}${text.slice(fileCompletion.tokenEnd)}`;
      const nextCursorPosition = fileCompletion.tokenStart + insertedText.length;

      onTextChange(nextText);
      closeFileCompletion();

      requestAnimationFrame(() => {
        const textarea = ref.current;
        if (!textarea) {
          return;
        }
        textarea.focus();
        textarea.setSelectionRange(nextCursorPosition, nextCursorPosition);
      });
    },
    [closeFileCompletion, fileCompletion, onTextChange, ref, text],
  );

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
    const maxHeight = singleLineHeight * 2;

    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [ref, text]);

  useEffect(() => {
    if (fileCompletion === null) {
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setFileCompletionLoading(true);
      void searchFileCompletions({
        sessionId,
        workDir: searchWorkDir,
        query: fileCompletion.searchQuery,
        signal: controller.signal,
      })
        .then((items) => {
          setFileCompletionItems(items);
          setFileCompletionHighlightIndex(0);
        })
        .catch((error) => {
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
          setFileCompletionItems([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setFileCompletionLoading(false);
          }
        });
    }, AT_COMPLETION_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [fileCompletion, searchWorkDir, sessionId]);

  useEffect(() => {
    if (!fileCompletionOpen) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        closeFileCompletion();
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [closeFileCompletion, fileCompletionOpen]);

  useEffect(() => {
    if (text.length === 0) {
      closeFileCompletion();
    }
  }, [closeFileCompletion, text]);

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
            updateFileCompletion(event.target.value, event.target.selectionStart);
          }}
          onSelect={(event) => {
            updateFileCompletion(event.currentTarget.value, event.currentTarget.selectionStart);
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
            if (fileCompletionOpen) {
              if (event.key === "ArrowDown" && fileCompletionItems.length > 0) {
                event.preventDefault();
                setFileCompletionHighlightIndex((current) =>
                  Math.min(current + 1, fileCompletionItems.length - 1),
                );
                return;
              }
              if (event.key === "ArrowUp" && fileCompletionItems.length > 0) {
                event.preventDefault();
                setFileCompletionHighlightIndex((current) => Math.max(current - 1, 0));
                return;
              }
              if (
                (event.key === "Enter" || event.key === "Tab") &&
                fileCompletionItems.length > 0
              ) {
                event.preventDefault();
                const path = fileCompletionItems[fileCompletionHighlightIndex];
                if (path) {
                  applyFileCompletion(path);
                }
                return;
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closeFileCompletion();
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
            onSubmit({ text, images: images.map((item) => item.image) });
          }}
          rows={1}
          placeholder={placeholder}
          className="min-h-[2rem] w-full resize-none overflow-y-hidden border-0 bg-transparent px-0 py-0.5 text-sm leading-7 text-neutral-800 outline-none placeholder:text-neutral-400"
        />
        {fileCompletionOpen ? (
          <AtFileCompletionList
            items={fileCompletionItems}
            loading={fileCompletionLoading}
            highlightIndex={fileCompletionHighlightIndex}
            onHighlightIndexChange={setFileCompletionHighlightIndex}
            onSelect={applyFileCompletion}
          />
        ) : null}
      </div>
      {images.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {images.map((attachment) => (
            <div
              key={attachment.id}
              className="group relative overflow-hidden rounded-md border border-neutral-200/80 bg-neutral-50"
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
        <div className="mt-2 text-xs text-neutral-500">
          Uploading {uploadingCount === 1 ? "image" : `${uploadingCount} images`}...
        </div>
      ) : null}
      {uploadError ? <div className="mt-2 text-xs text-red-500">{uploadError}</div> : null}
      <div className="mt-1 flex items-center justify-between gap-3">
        <ModelSelector
          options={modelOptions}
          value={modelValue}
          loading={modelLoading}
          disabled={modelDisabled}
          placeholder={modelPlaceholder}
          onSelect={onModelSelect}
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
                <ImagePlus className="h-4 w-4" strokeWidth={2.2} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Add image or paste from clipboard</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={
                  interruptible
                    ? onInterrupt
                    : () => onSubmit({ text, images: images.map((item) => item.image) })
                }
                disabled={buttonDisabled}
                aria-label={buttonLabel}
                className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white transition-colors disabled:cursor-not-allowed ${
                  interruptible
                    ? "bg-amber-600 hover:bg-amber-500 disabled:bg-amber-200 disabled:text-amber-50"
                    : "bg-neutral-800 hover:bg-neutral-700 disabled:bg-neutral-200 disabled:text-neutral-400"
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
