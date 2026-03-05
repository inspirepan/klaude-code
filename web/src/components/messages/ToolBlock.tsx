import { useState } from "react";
import { ChevronRight, Loader2 } from "lucide-react";

import type { ToolBlockItem } from "../../types/message";
import { DiffView } from "./DiffView";

// Tools whose result is expanded by default
const EXPAND_RESULT_TOOLS = new Set([
  "diff",
  "read_preview",
  "todo_list",
  "ask_user_question_summary",
  "image",
]);

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

function shouldExpandResult(item: ToolBlockItem): boolean {
  if (item.resultStatus === "error") return false;
  if (item.toolName === "Read") return false;
  if (item.uiExtra !== null) return true;
  if (EXPAND_RESULT_TOOLS.has(item.toolName)) return true;
  return false;
}

interface ToolBlockProps {
  item: ToolBlockItem;
}

const RESULT_LINE_LIMIT = 15;

export function ToolBlock({ item }: ToolBlockProps): JSX.Element {
  const defaultExpanded = shouldExpandResult(item);
  const [open, setOpen] = useState(defaultExpanded);
  const [showMore, setShowMore] = useState(false);

  const detail = extractHeaderDetail(item.toolName, item.arguments);
  const isBash = item.toolName === "Bash";
  const hasResult = item.result !== null && item.result.length > 0;
  const isError = item.resultStatus === "error";
  const hasDiff = item.uiExtra !== null && (item.uiExtra as Record<string, unknown>).type === "diff";
  const expandable = hasResult || hasDiff;

  const detailColor = isError
    ? "text-red-700"
    : item.resultStatus === "aborted"
      ? "text-zinc-400"
      : "text-zinc-400";

  return (
    <div
      className={`grid grid-cols-[auto_1fr] gap-x-1.5 items-start text-[15px] font-mono ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => expandable && setOpen((v) => !v)}
    >
      {/* left col: chevron + vertical line + tool name */}
      <div className="flex items-start gap-1.5 self-stretch">
        <div className="flex flex-col items-center self-stretch">
          <ChevronRight
            className={`w-4 h-4 text-zinc-300 transition-transform duration-150 shrink-0 mt-1 ${open ? "rotate-90" : ""} ${!expandable ? "opacity-0" : ""}`}
          />
          {open ? <div className="w-px bg-zinc-200 flex-1 mt-1" /> : null}
        </div>
        <span className="font-normal text-zinc-500 whitespace-nowrap font-sans tracking-[0.03em]">{item.toolName}</span>
        {item.isStreaming ? (
          <Loader2 className="w-3 h-3 text-zinc-400 animate-spin shrink-0 mt-0.5" />
        ) : null}
      </div>

      {/* right col: detail (truncated or wrapped) + result */}
      <div className="min-w-0">
        {detail ? (
          isBash ? (
            <code className={`inline-block max-w-full text-sm bg-zinc-100 rounded px-1.5 py-0.5 ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}>
              {detail}
            </code>
          ) : (
            <span className={`inline-block max-w-full text-sm bg-zinc-100 rounded px-1.5 py-0.5 ${open ? "whitespace-pre-wrap break-words" : "truncate"} ${detailColor}`}>
              {detail}
            </span>
          )
        ) : null}
        {open ? (
          hasDiff ? (
            <div className="mt-1 rounded-lg border border-zinc-200/80 overflow-hidden">
              <DiffView item={item} />
            </div>
          ) : hasResult ? (() => {
            const lines = item.result!.split("\n");
            const truncated = !showMore && lines.length > RESULT_LINE_LIMIT;
            const displayed = truncated ? lines.slice(0, RESULT_LINE_LIMIT).join("\n") : item.result!;
            return (
              <div onClick={(e) => e.stopPropagation()}>
                <pre
                  className={`mt-1 text-sm leading-relaxed whitespace-pre-wrap break-words font-mono ${
                    isError ? "text-red-700" : "text-zinc-400"
                  }`}
                >
                  {displayed}
                </pre>
                {lines.length > RESULT_LINE_LIMIT ? (
                  <button
                    type="button"
                    onClick={() => setShowMore((v) => !v)}
                    className="mt-1 text-xs text-zinc-400 hover:text-zinc-600 cursor-pointer transition-colors font-sans"
                  >
                    {showMore ? "Show less" : `Show more (${lines.length - RESULT_LINE_LIMIT} lines)`}
                  </button>
                ) : null}
              </div>
            );
          })() : null
        ) : null}
      </div>
    </div>
  );
}
