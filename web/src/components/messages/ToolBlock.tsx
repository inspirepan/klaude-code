import { useState, useMemo, useRef, useEffect } from "react";
import { ChevronRight, Loader2 } from "lucide-react";

import type { ToolBlockItem } from "../../types/message";
import { useSearch } from "./search-context";
import { HighlightText } from "./HighlightText";
import { DiffView } from "./DiffView";
import { FilePath } from "./FilePath";
import { TodoListView } from "./TodoListView";
import { MarkdownDocView } from "./MarkdownDocView";
import { QuestionSummaryView } from "./QuestionSummaryView";
import { ImageResultView } from "./ImageResultView";
import {
  isDiffUIExtra,
  isImageUIExtra,
  isMarkdownDocUIExtra,
  isQuestionSummaryUIExtra,
  isTodoListUIExtra,
} from "./message-ui-extra";

const PLAN_TOOLS = new Set(["TodoWrite", "update_plan"]);
const FILE_PATH_TOOLS = new Set(["Read", "Edit", "Write", "Glob", "Grep"]);

function extractHeaderDetail(toolName: string, args: string): string {
  try {
    const parsed = JSON.parse(args);
    switch (toolName) {
      case "Bash":
        return typeof parsed.command === "string" ? parsed.command : "";
      case "Read":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "Edit":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "Write":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "apply_patch": {
        const patch = typeof parsed.patch === "string" ? parsed.patch : "";
        const updates: string[] = [];
        const adds: string[] = [];
        const deletes: string[] = [];
        for (const line of patch.split("\n")) {
          if (line.startsWith("*** Update File:")) updates.push(line.slice(16).trim());
          else if (line.startsWith("*** Add File:")) adds.push(line.slice(13).trim());
          else if (line.startsWith("*** Delete File:")) deletes.push(line.slice(16).trim());
        }
        const parts: string[] = [];
        if (updates.length) parts.push(`Edit x${updates.length}`);
        if (adds.length) parts.push(`Create x${adds.length}`);
        if (deletes.length) parts.push(`Delete x${deletes.length}`);
        return parts.join(", ");
      }
      case "WebFetch":
        return typeof parsed.url === "string" ? parsed.url : "";
      case "WebSearch":
        return typeof parsed.query === "string" ? parsed.query : "";
      case "Glob":
        return typeof parsed.pattern === "string" ? parsed.pattern : "";
      case "Grep":
        return typeof parsed.pattern === "string" ? parsed.pattern : "";
      default:
        return "";
    }
  } catch {
    return "";
  }
}

function hasRichUIExtra(extra: Record<string, unknown>): boolean {
  if (
    isDiffUIExtra(extra) ||
    isTodoListUIExtra(extra) ||
    isMarkdownDocUIExtra(extra) ||
    isQuestionSummaryUIExtra(extra) ||
    isImageUIExtra(extra)
  )
    return true;
  if (extra.type === "multi" && Array.isArray(extra.items)) {
    return (extra.items as Record<string, unknown>[]).some(hasRichUIExtra);
  }
  return false;
}

function hasDiffUIExtra(extra: Record<string, unknown>): boolean {
  if (isDiffUIExtra(extra)) return true;
  if (extra.type === "multi" && Array.isArray(extra.items)) {
    return (extra.items as Record<string, unknown>[]).some(hasDiffUIExtra);
  }
  return false;
}

function shouldExpandResult(item: ToolBlockItem): boolean {
  if (item.resultStatus === "error") return false;
  if (item.uiExtra !== null && hasRichUIExtra(item.uiExtra)) return true;
  if (item.toolName === "Read") return false;
  return false;
}

function RichUIExtraBlock({
  extra,
  item,
  compact,
}: {
  extra: Record<string, unknown>;
  item: ToolBlockItem;
  compact: boolean;
}): JSX.Element | null {
  if (isDiffUIExtra(extra)) {
    return (
      <div className="mt-0.5 overflow-hidden rounded-lg border border-neutral-200/80">
        <DiffView item={item} uiExtra={extra} />
      </div>
    );
  }
  if (isTodoListUIExtra(extra)) {
    return <TodoListView uiExtra={extra} compact={compact} />;
  }
  if (isMarkdownDocUIExtra(extra)) {
    return <MarkdownDocView uiExtra={extra} compact={compact} />;
  }
  if (isQuestionSummaryUIExtra(extra)) {
    return (
      <div className="rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2.5">
        <QuestionSummaryView uiExtra={extra} compact={compact} />
      </div>
    );
  }
  if (isImageUIExtra(extra)) {
    return <ImageResultView uiExtra={extra} compact={compact} />;
  }
  return null;
}

function RichResult({
  item,
  compact,
}: {
  item: ToolBlockItem;
  compact: boolean;
}): JSX.Element | null {
  const extra = item.uiExtra;
  if (!extra) return null;

  if (extra.type === "multi" && Array.isArray(extra.items)) {
    const items = extra.items as Record<string, unknown>[];
    return (
      <div className="flex flex-col gap-1">
        {items.map((sub, i) => (
          <RichUIExtraBlock key={i} extra={sub} item={item} compact={compact} />
        ))}
      </div>
    );
  }

  return <RichUIExtraBlock extra={extra} item={item} compact={compact} />;
}

interface ToolBlockProps {
  item: ToolBlockItem;
  compact?: boolean;
  workDir?: string;
}

const RESULT_LINE_LIMIT = 15;

function extractPlanExplanation(args: string): string {
  try {
    const parsed = JSON.parse(args);
    if (typeof parsed.explanation === "string") return parsed.explanation.trim();
  } catch {
    /* ignore */
  }
  return "";
}

function PlanBlock({ item, compact = false }: ToolBlockProps): JSX.Element {
  const explanation = useMemo(() => {
    if (item.toolName === "update_plan") return extractPlanExplanation(item.arguments);
    return "";
  }, [item.toolName, item.arguments]);

  const todoExtra = item.uiExtra && isTodoListUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div
      className={`rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2 ${compact ? "text-[13px]" : "text-[14px]"}`}
    >
      {explanation ? (
        <p className={`${compact ? "text-[13px]" : "text-sm"} mb-1 font-sans text-neutral-500`}>
          {explanation}
        </p>
      ) : null}
      {todoExtra ? (
        <TodoListView uiExtra={todoExtra} compact={compact} />
      ) : item.isStreaming ? (
        <div
          className={`flex items-center gap-1.5 text-neutral-400 ${compact ? "text-[13px]" : "text-sm"} font-sans`}
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          <span>Planning…</span>
        </div>
      ) : null}
    </div>
  );
}

function QuestionBlock({ item, compact = false }: ToolBlockProps): JSX.Element {
  const questionExtra =
    item.uiExtra && isQuestionSummaryUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div
      className={`rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2 ${compact ? "text-[13px]" : "text-[14px]"}`}
    >
      {questionExtra ? (
        <QuestionSummaryView uiExtra={questionExtra} compact={compact} />
      ) : item.isStreaming ? (
        <div
          className={`flex items-center gap-1.5 text-neutral-400 ${compact ? "text-[13px]" : "text-sm"} font-sans`}
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          <span>Waiting for answer…</span>
        </div>
      ) : null}
    </div>
  );
}

export function ToolBlock({ item, compact = false, workDir }: ToolBlockProps): JSX.Element {
  const { matchItemIds } = useSearch();
  const bodyTextClass = compact ? "text-[13px]" : "text-[14px]";
  const subTextClass = compact ? "text-[13px]" : "text-sm";
  const headerDetailTextClass = "!text-[13px]";
  const miniTextClass = compact ? "text-[11px]" : "text-xs";
  const detailChipClass = "rounded bg-neutral-100 px-1.5 py-0.5 align-middle";

  const defaultExpanded = shouldExpandResult(item);
  const [open, setOpen] = useState(defaultExpanded);
  const [showMore, setShowMore] = useState(false);
  const isSearchMatch = matchItemIds.includes(item.id);
  const wasAutoExpanded = useRef(false);

  // Auto-expand when search matches inside this tool block
  useEffect(() => {
    if (isSearchMatch && !open) {
      setOpen(true);
      wasAutoExpanded.current = true;
    }
    if (!isSearchMatch && wasAutoExpanded.current) {
      setOpen(defaultExpanded);
      wasAutoExpanded.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSearchMatch]);

  if (PLAN_TOOLS.has(item.toolName)) {
    return <PlanBlock item={item} compact={compact} />;
  }
  if (item.toolName === "AskUserQuestion") {
    return <QuestionBlock item={item} compact={compact} />;
  }

  const detail = extractHeaderDetail(item.toolName, item.arguments);
  const isBash = item.toolName === "Bash";
  const hasResult = item.result !== null && item.result.length > 0;
  const isEmptyResult = item.result !== null && item.result.length === 0;
  const isError = item.resultStatus === "error";
  const hasRich = item.uiExtra !== null && hasRichUIExtra(item.uiExtra);
  const hideResultRail = item.uiExtra !== null && hasDiffUIExtra(item.uiExtra);
  const expandable = hasResult || isEmptyResult || hasRich;

  const detailColor = isError
    ? "text-red-700"
    : item.resultStatus === "aborted"
      ? "text-neutral-400"
      : "text-neutral-400";

  return (
    <div
      className={`-my-1 grid grid-cols-[auto_1fr] items-baseline gap-x-1.5 ${bodyTextClass} font-mono ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => expandable && setOpen((v) => !v)}
    >
      {/* left col: chevron + vertical line + tool name */}
      <div className="flex items-baseline gap-1.5 self-stretch">
        <div className="flex flex-col items-center self-stretch">
          <ChevronRight
            className={`mt-1 h-4 w-4 shrink-0 text-neutral-300 transition-transform duration-150 ${open ? "rotate-90" : ""} ${!expandable ? "opacity-0" : ""}`}
          />
          {open ? <div className="mt-1 w-px flex-1 bg-neutral-200" /> : null}
        </div>
        <span className="relative top-[2px] whitespace-nowrap font-sans font-normal text-neutral-500">
          {item.toolName}
        </span>
        {item.isStreaming ? (
          <Loader2 className="mt-0.5 h-3 w-3 shrink-0 translate-y-px animate-spin text-neutral-400" />
        ) : null}
      </div>

      {/* right col: detail only */}
      <div className="min-w-0">
        {detail ? (
          FILE_PATH_TOOLS.has(item.toolName) ? (
            <FilePath
              path={detail}
              expanded={open}
              workDir={workDir}
              className={headerDetailTextClass}
            />
          ) : isBash ? (
            <code
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </code>
          ) : (
            <span
              className={`inline-block max-w-full ${headerDetailTextClass} ${detailChipClass} ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}
            >
              <HighlightText>{detail}</HighlightText>
            </span>
          )
        ) : null}
      </div>

      {/* result: full width */}
      {open ? (
        <div className="col-span-2 mt-0.5 grid min-w-0 grid-cols-[16px_1fr] gap-x-1.5">
          <div className="flex justify-center">
            {hideResultRail ? null : <div className="w-px bg-neutral-200" />}
          </div>
          <div className="min-w-0">
            {hasRich ? (
              <div onClick={(e) => e.stopPropagation()}>
                <RichResult item={item} compact={compact} />
              </div>
            ) : hasResult ? (
              (() => {
                const lines = item.result!.split("\n");
                const truncated = !showMore && lines.length > RESULT_LINE_LIMIT;
                const displayed = truncated
                  ? lines.slice(0, RESULT_LINE_LIMIT).join("\n")
                  : item.result!;
                return (
                  <div onClick={(e) => e.stopPropagation()}>
                    <pre
                      className={`mt-0.5 ${subTextClass} whitespace-pre-wrap break-words font-mono leading-relaxed ${
                        isError ? "text-red-700" : "text-neutral-400"
                      }`}
                    >
                      <HighlightText>{displayed}</HighlightText>
                    </pre>
                    {lines.length > RESULT_LINE_LIMIT ? (
                      <button
                        type="button"
                        onClick={() => setShowMore((v) => !v)}
                        className={`mt-0.5 ${miniTextClass} cursor-pointer font-sans text-neutral-400 transition-colors hover:text-neutral-600`}
                      >
                        {showMore
                          ? "Show less"
                          : `Show more (${lines.length - RESULT_LINE_LIMIT} lines)`}
                      </button>
                    ) : null}
                  </div>
                );
              })()
            ) : isEmptyResult ? (
              <div className={`mt-0.5 ${subTextClass} font-mono text-neutral-400`}>
                (no content)
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
