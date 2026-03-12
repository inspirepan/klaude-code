import { useEffect, useRef } from "react";
import { ArrowUp } from "lucide-react";

import type { ConfigModelSummary } from "../../api/client";
import { ModelSelector } from "./ModelSelector";

interface ComposerCardProps {
  text: string;
  onTextChange: (text: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  disableSubmit: boolean;
  placeholder?: string;
  modelOptions: ConfigModelSummary[];
  modelValue: string;
  modelLoading?: boolean;
  modelDisabled?: boolean;
  modelPlaceholder?: string;
  onModelSelect: (modelName: string) => void;
  textareaRef?: React.RefObject<HTMLTextAreaElement>;
  /** Open model dropdown above (default) or below the trigger. */
  modelDropUp?: boolean;
}

export function ComposerCard({
  text,
  onTextChange,
  onSubmit,
  submitting,
  disableSubmit,
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
  const ref = externalRef ?? internalRef;

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

  return (
    <div className="rounded-2xl bg-white px-4 py-2.5 shadow-sm ring-1 ring-black/[0.06]">
      <textarea
        ref={ref}
        value={text}
        onChange={(event) => {
          onTextChange(event.target.value);
        }}
        onKeyDown={(event) => {
          if (event.nativeEvent.isComposing || event.key !== "Enter" || event.shiftKey) {
            return;
          }
          event.preventDefault();
          onSubmit();
        }}
        rows={1}
        placeholder={placeholder}
        className="min-h-[2rem] w-full resize-none overflow-y-hidden border-0 bg-transparent px-0 py-0.5 text-[15px] leading-7 text-neutral-800 outline-none placeholder:text-neutral-400"
      />
      <div className="mt-1 flex items-center justify-between">
        <ModelSelector
          options={modelOptions}
          value={modelValue}
          loading={modelLoading}
          disabled={modelDisabled}
          placeholder={modelPlaceholder}
          onSelect={onModelSelect}
          dropUp={modelDropUp}
        />
        <button
          type="button"
          onClick={onSubmit}
          disabled={disableSubmit}
          aria-label={submitting ? "Sending" : "Send"}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-neutral-800 text-white transition-colors hover:bg-neutral-700 disabled:cursor-not-allowed disabled:bg-neutral-200 disabled:text-neutral-400"
        >
          <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
