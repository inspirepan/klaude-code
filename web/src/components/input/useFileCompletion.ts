import { useCallback, useEffect, useState, type RefObject } from "react";
import { searchFileCompletions } from "../../api/client";

const AT_COMPLETION_PATTERN = /(^|\s)@(?<frag>"[^"]*"|[^\s]*)$/;
const AT_COMPLETION_DEBOUNCE_MS = 120;

export interface FileCompletionContext {
  fragment: string;
  searchQuery: string;
  tokenStart: number;
  tokenEnd: number;
  isQuoted: boolean;
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

interface UseFileCompletionOptions {
  sessionId: string;
  searchWorkDir?: string;
  text: string;
  onTextChange: (text: string) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
}

export interface FileCompletionState {
  items: string[];
  loading: boolean;
  highlightIndex: number;
  open: boolean;
  setHighlightIndex: (index: number) => void;
  update: (nextText: string, cursorPosition: number | null) => void;
  apply: (path: string) => void;
  close: () => void;
}

export function useFileCompletion({
  sessionId,
  searchWorkDir,
  text,
  onTextChange,
  textareaRef,
}: UseFileCompletionOptions): FileCompletionState {
  const [fileCompletion, setFileCompletion] = useState<FileCompletionContext | null>(null);
  const [items, setItems] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);

  const open = loading || items.length > 0;

  const close = useCallback(() => {
    setFileCompletion(null);
    setItems([]);
    setLoading(false);
    setHighlightIndex(0);
  }, []);

  const update = useCallback((nextText: string, cursorPosition: number | null) => {
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
      setItems([]);
      setLoading(false);
    }
    setHighlightIndex(0);
  }, []);

  const apply = useCallback(
    (path: string) => {
      if (fileCompletion === null) {
        return;
      }

      const insertedText = formatFileCompletionText(path, fileCompletion.isQuoted);
      const nextText = `${text.slice(0, fileCompletion.tokenStart)}${insertedText}${text.slice(fileCompletion.tokenEnd)}`;
      const nextCursorPosition = fileCompletion.tokenStart + insertedText.length;

      onTextChange(nextText);
      close();

      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) {
          return;
        }
        textarea.focus();
        textarea.setSelectionRange(nextCursorPosition, nextCursorPosition);
      });
    },
    [close, fileCompletion, onTextChange, textareaRef, text],
  );

  useEffect(() => {
    if (fileCompletion === null) {
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      setLoading(true);
      void searchFileCompletions({
        sessionId,
        workDir: searchWorkDir,
        query: fileCompletion.searchQuery,
        signal: controller.signal,
      })
        .then((completionItems) => {
          setItems(completionItems);
          setHighlightIndex(0);
        })
        .catch((error) => {
          if (error instanceof DOMException && error.name === "AbortError") {
            return;
          }
          setItems([]);
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setLoading(false);
          }
        });
    }, AT_COMPLETION_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [fileCompletion, searchWorkDir, sessionId]);

  return { items, loading, highlightIndex, open, setHighlightIndex, update, apply, close };
}
