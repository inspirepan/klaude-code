import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, MessageSquare, Search } from "lucide-react";
import { searchSessions, type SessionSearchResult } from "@/api/client";
import { CommandListItem, CommandListPanel, CommandListScroll } from "@/components/ui/command-list";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useT } from "@/i18n";

function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((s) => s.length > 0);
  return parts[parts.length - 1] ?? workDir;
}

/** Render text with the first case-insensitive match of `query` highlighted. */
function HighlightedText({
  text,
  query,
  className,
}: {
  text: string;
  query: string;
  className?: string;
}): React.JSX.Element {
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <span className={className}>{text}</span>;
  return (
    <span className={className}>
      {text.slice(0, idx)}
      <mark className="bg-amber-200/60 text-inherit">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </span>
  );
}

const CONTEXT_CHARS = 28;
const MAX_SNIPPETS = 3;

interface MatchSnippet {
  before: string;
  match: string;
  after: string;
  ellipsisBefore: boolean;
  ellipsisAfter: boolean;
}

/**
 * Extract up to `MAX_SNIPPETS` KWIC (keyword-in-context) snippets from `text`.
 * Each snippet has ~CONTEXT_CHARS characters of surrounding context.
 */
function extractSnippets(text: string, query: string): MatchSnippet[] {
  const textLower = text.toLowerCase();
  const queryLower = query.toLowerCase();
  const qLen = query.length;
  const snippets: MatchSnippet[] = [];
  let searchFrom = 0;

  while (snippets.length < MAX_SNIPPETS) {
    const idx = textLower.indexOf(queryLower, searchFrom);
    if (idx === -1) break;

    const ctxStart = Math.max(0, idx - CONTEXT_CHARS);
    const ctxEnd = Math.min(text.length, idx + qLen + CONTEXT_CHARS);

    snippets.push({
      before: text.slice(ctxStart, idx),
      match: text.slice(idx, idx + qLen),
      after: text.slice(idx + qLen, ctxEnd),
      ellipsisBefore: ctxStart > 0,
      ellipsisAfter: ctxEnd < text.length,
    });

    searchFrom = idx + qLen;
  }
  return snippets;
}

/** Render KWIC snippets with highlights, separated by " ... ". */
function SnippetText({
  snippets,
  className,
}: {
  snippets: MatchSnippet[];
  className?: string;
}): React.JSX.Element {
  return (
    <span className={className}>
      {snippets.map((s, i) => (
        <span key={i}>
          {i > 0 ? <span className="text-neutral-400"> ... </span> : null}
          {s.ellipsisBefore && i === 0 ? "\u2026" : null}
          {s.before}
          <mark className="bg-amber-200/60 text-inherit">{s.match}</mark>
          {s.after}
          {s.ellipsisAfter && i === snippets.length - 1 ? "\u2026" : null}
        </span>
      ))}
    </span>
  );
}

/** Find the first user message containing the query (case-insensitive). */
function findMatchedUserMessage(result: SessionSearchResult, queryLower: string): string | null {
  for (const msg of result.user_messages) {
    if (msg.toLowerCase().includes(queryLower)) {
      return msg;
    }
  }
  return null;
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "\u2026" : text;
}

interface SessionSearchProps {
  onSelectSession: (sessionId: string, archived: boolean, workDir: string) => void;
  onOpenChange?: (open: boolean) => void;
  onBeforeOpen?: () => void;
}

export function SessionSearch({
  onSelectSession,
  onOpenChange,
  onBeforeOpen,
}: SessionSearchProps): React.JSX.Element {
  const t = useT();
  const [open, setOpenRaw] = useState(false);
  const setOpen = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      setOpenRaw((prev) => {
        const value = typeof next === "function" ? next(prev) : next;
        if (value !== prev) onOpenChange?.(value);
        return value;
      });
    },
    [onOpenChange],
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SessionSearchResult[]>([]);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const [searched, setSearched] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handleClose = useCallback(() => {
    setOpen(false);
    setQuery("");
    setResults([]);
    setHighlightIndex(-1);
    setSearched(false);
  }, [setOpen]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: PointerEvent): void => {
      if (!containerRef.current?.contains(e.target as Node)) {
        handleClose();
      }
    };
    const handleKeyDown = (e: KeyboardEvent): void => {
      if (e.key === "Escape") {
        handleClose();
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, handleClose]);

  // Focus input when opened
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Debounced search
  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    if (!trimmed) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const timeout = window.setTimeout(() => {
      void searchSessions(trimmed, controller.signal)
        .then((items) => {
          if (!controller.signal.aborted) {
            setResults(items);
            setHighlightIndex(items.length > 0 ? 0 : -1);
            setSearched(true);
          }
        })
        .catch(() => {});
    }, 200);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [query, open]);

  const handleSelect = useCallback(
    (result: SessionSearchResult) => {
      handleClose();
      onSelectSession(result.id, result.archived, result.work_dir);
    },
    [handleClose, onSelectSession],
  );

  const handleInputKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIndex((prev) => (prev < results.length - 1 ? prev + 1 : prev));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIndex((prev) => (prev > 0 ? prev - 1 : prev));
    } else if (e.key === "Enter" && highlightIndex >= 0 && highlightIndex < results.length) {
      e.preventDefault();
      handleSelect(results[highlightIndex]);
    }
  };

  const trimmedQuery = query.trim();
  // Derive display values so we don't need to setState when query becomes empty
  const visibleResults = trimmedQuery ? results : [];
  const visibleSearched = trimmedQuery ? searched : false;

  return (
    <div ref={containerRef} className="relative">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
            onClick={() => {
              if (open) {
                handleClose();
              } else {
                onBeforeOpen?.();
                setOpen(true);
              }
            }}
            aria-label={t("sidebar.searchSessions")}
          >
            <Search className="h-4 w-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent>{t("sidebar.searchSessions")}</TooltipContent>
      </Tooltip>

      {open ? (
        <CommandListPanel className="absolute bottom-full left-0 z-40 mb-2 w-[380px] max-w-[calc(100vw-2rem)] shadow-float-lg">
          <div className="border-b border-border/60 px-2.5 py-2">
            <div className="flex items-center gap-2">
              <Search className="h-3.5 w-3.5 shrink-0 text-neutral-400" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                }}
                onKeyDown={handleInputKeyDown}
                placeholder={t("sidebar.searchPlaceholder")}
                className="min-w-0 flex-1 bg-transparent text-sm text-neutral-800 outline-none placeholder:text-neutral-400"
              />
            </div>
          </div>
          {visibleSearched && visibleResults.length === 0 ? (
            <div className="px-3 py-3 text-sm text-neutral-500">{t("sidebar.noSearchResults")}</div>
          ) : null}
          {visibleResults.length > 0 ? (
            <CommandListScroll maxHeight="max-h-80">
              {visibleResults.map((result, index) => (
                <SearchResultItem
                  key={result.id}
                  result={result}
                  query={trimmedQuery}
                  highlighted={index === highlightIndex}
                  fallbackTitle={t("sidebar.newSession")}
                  onClick={() => {
                    handleSelect(result);
                  }}
                  onPointerMove={() => {
                    setHighlightIndex(index);
                  }}
                />
              ))}
            </CommandListScroll>
          ) : null}
        </CommandListPanel>
      ) : null}
    </div>
  );
}

function SearchResultItem({
  result,
  query,
  highlighted,
  fallbackTitle,
  onClick,
  onPointerMove,
}: {
  result: SessionSearchResult;
  query: string;
  highlighted: boolean;
  fallbackTitle: string;
  onClick: () => void;
  onPointerMove: () => void;
}): React.JSX.Element {
  const queryLower = query.toLowerCase();
  const title = result.title?.trim();
  const displayTitle = title || result.user_messages[0]?.trim() || fallbackTitle;

  // Determine if a user message (other than the one already used as display title) matched
  const matchedUserMsg = findMatchedUserMessage(result, queryLower);
  const titleAlreadyShowsMatch =
    matchedUserMsg !== null && !title && matchedUserMsg === result.user_messages[0];

  const showMatchedMsg = matchedUserMsg !== null && !titleAlreadyShowsMatch;
  const snippets = showMatchedMsg ? extractSnippets(matchedUserMsg, query) : [];

  return (
    <CommandListItem highlighted={highlighted} onClick={onClick} onPointerMove={onPointerMove}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <HighlightedText
            text={truncate(displayTitle, 80)}
            query={query}
            className="truncate text-sm"
          />
          {result.archived ? <Archive className="h-3 w-3 shrink-0 text-neutral-400" /> : null}
        </div>
        {snippets.length > 0 ? (
          <div className="mt-0.5 flex items-start gap-1">
            <MessageSquare className="mt-0.5 h-3 w-3 shrink-0 text-neutral-400" />
            <SnippetText snippets={snippets} className="line-clamp-2 text-xs text-neutral-500" />
          </div>
        ) : null}
        <HighlightedText
          text={workDirLabel(result.work_dir)}
          query={query}
          className="truncate text-xs text-neutral-400"
        />
      </div>
    </CommandListItem>
  );
}
