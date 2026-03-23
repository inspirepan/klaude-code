import { parse as shellParse } from "shell-quote";
import { useEffect, useMemo, useRef, useState } from "react";

import { useT } from "@/i18n";
import type { MessageItem as MessageItemType, DeveloperMessageItem } from "../../types/message";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailConnector,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import { isDiffUIExtra } from "./message-ui-extra";
import { MessageRow } from "./MessageRow";
import { DeveloperMessage } from "./DeveloperMessage";

interface CollapseGroupBlockProps {
  items: MessageItemType[];
  collapsed: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

// Commands that take a meaningful subcommand as their second token
const SUBCOMMAND_COMMANDS = new Set([
  // Version control
  "git",
  "jj",
  "hg",
  "svn",
  // Containers & orchestration
  "docker",
  "docker-compose",
  "podman",
  "kubectl",
  "helm",
  "minikube",
  // JS package managers
  "npm",
  "yarn",
  "pnpm",
  "bun",
  "deno",
  // Rust
  "cargo",
  "rustup",
  // Python
  "uv",
  "pip",
  "pipx",
  "poetry",
  "conda",
  "python",
  // Ruby
  "ruby",
  "gem",
  "bundle",
  // Other languages
  "go",
  "dotnet",
  "swift",
  "mix",
  "gradle",
  // System package managers
  "brew",
  "apt",
  "apt-get",
  "dnf",
  "yum",
  "pacman",
  // Cloud & infra
  "aws",
  "gcloud",
  "az",
  "terraform",
  "pulumi",
  "fly",
  "vercel",
  "netlify",
  "heroku",
  "wrangler",
  // Build tools
  "make",
  "just",
  "nx",
  "turbo",
  "bazel",
  // CLI tools
  "gh",
  // Service managers
  "systemctl",
  "launchctl",
  "supervisorctl",
]);

interface FileStat {
  name: string;
  del?: number;
  add: number;
}

interface SummaryPart {
  label: string;
  value: string;
  del?: number;
  add?: number;
  fileStats?: FileStat[];
}

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

const IGNORED_COMMANDS = new Set(["cd"]);


// Operators that separate independent statements (we extract a command from each)
const STATEMENT_SEPARATORS = new Set(["&&", "||", ";", "\n"]);

function extractBashSummaries(command: string): string[] {
  const tokens = shellParse(command);

  // Split token stream into statements on control operators
  const statements: string[][] = [];
  let current: string[] = [];

  for (const tok of tokens) {
    if (typeof tok === "object" && "op" in tok) {
      if (STATEMENT_SEPARATORS.has(tok.op)) {
        if (current.length > 0) statements.push(current);
        current = [];
        continue;
      }
      // Pipe | and redirections are part of the same statement; skip the operator
      continue;
    }
    if (typeof tok === "string") {
      current.push(tok);
    }
  }
  if (current.length > 0) statements.push(current);

  // Extract command name from each statement
  const summaries: string[] = [];
  for (const words of statements) {
    if (words.length === 0) continue;
    const cmd = words[0]!;
    if (IGNORED_COMMANDS.has(cmd)) continue;
    if (SUBCOMMAND_COMMANDS.has(cmd)) {
      const sub = words.slice(1).find((w) => !w.startsWith("-"));
      if (sub) {
        summaries.push(`${cmd} ${sub}`);
        continue;
      }
    }
    summaries.push(cmd);
  }
  return summaries;
}

function extractApplyPatchFileStats(patch: string): FileStat[] {
  const fileStats: FileStat[] = [];
  let current: FileStat | null = null;

  const pushCurrent = () => {
    if (current !== null) fileStats.push(current);
  };

  for (const line of patch.split("\n")) {
    if (line.startsWith("*** Update File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(17).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** Add File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(13).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** Delete File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(16).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** ")) continue;
    if (current === null) continue;
    if (line.startsWith("+")) current.add += 1;
    else if (line.startsWith("-")) current.del = (current.del ?? 0) + 1;
  }

  pushCurrent();
  if (fileStats.length > 0) return fileStats;

  let unifiedCurrent: FileStat | null = null;
  for (const line of patch.split("\n")) {
    const fileMatch = line.match(/^\+\+\+ b\/(.+)$/) ?? line.match(/^--- a\/(.+)$/);
    if (fileMatch) {
      const name = basename(fileMatch[1]!);
      if (unifiedCurrent === null || unifiedCurrent.name !== name) {
        if (unifiedCurrent !== null) fileStats.push(unifiedCurrent);
        unifiedCurrent = { name, del: 0, add: 0 };
      }
      continue;
    }
    if (line.startsWith("+++ ") || line.startsWith("--- ")) continue;
    if (unifiedCurrent === null) continue;
    if (line.startsWith("+")) unifiedCurrent.add += 1;
    else if (line.startsWith("-")) unifiedCurrent.del = (unifiedCurrent.del ?? 0) + 1;
  }

  if (unifiedCurrent !== null) fileStats.push(unifiedCurrent);
  return fileStats;
}

function extractDiffStats(uiExtra: Record<string, unknown> | null): { del: number; add: number } | null {
  if (!uiExtra) return null;
  const extras = isDiffUIExtra(uiExtra)
    ? [uiExtra]
    : uiExtra.type === "multi" && Array.isArray(uiExtra.items)
      ? (uiExtra.items as Record<string, unknown>[]).filter(isDiffUIExtra)
      : [];
  if (extras.length === 0) return null;
  let del = 0;
  let add = 0;
  for (const extra of extras) {
    for (const file of extra.files) {
      del += file.stats_remove;
      add += file.stats_add;
    }
  }
  return { del, add };
}

function summarizeCollapseItems(
  items: MessageItemType[],
  t: ReturnType<typeof useT>,
): SummaryPart[] {
  const grouped = new Map<string, string[]>();
  // Parallel stats for file-editing tools: [{ del, add }] per invocation
  const editStats = new Map<string, Array<{ del: number; add: number }>>();

  for (const item of items) {
    if (item.type !== "tool_block") continue;
    let args: Record<string, unknown>;
    try {
      args = JSON.parse(item.arguments) as Record<string, unknown>;
    } catch {
      continue;
    }

    const name = item.toolName;
    if (!grouped.has(name)) grouped.set(name, []);
    const bucket = grouped.get(name)!;

    switch (name) {
      case "Read": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (p) bucket.push(p);
        break;
      }
      case "Edit": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (!p) break;
        const diffStats = extractDiffStats(item.uiExtra);
        const del = diffStats?.del ?? (typeof args.old_string === "string" ? args.old_string.split("\n").length : 0);
        const add = diffStats?.add ?? (typeof args.new_string === "string" ? args.new_string.split("\n").length : 0);
        bucket.push(p);
        if (!editStats.has(name)) editStats.set(name, []);
        editStats.get(name)!.push({ del, add });
        break;
      }
      case "Write": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (!p) break;
        const diffStats = extractDiffStats(item.uiExtra);
        const add = diffStats?.add ?? (typeof args.content === "string" ? args.content.split("\n").length : 0);
        bucket.push(p);
        if (!editStats.has(name)) editStats.set(name, []);
        editStats.get(name)!.push({ del: diffStats?.del ?? 0, add });
        break;
      }
      case "apply_patch": {
        const patch = typeof args.patch === "string" ? args.patch : null;
        if (!patch) break;
        const fileStats = extractApplyPatchFileStats(patch);
        if (!editStats.has(name)) editStats.set(name, []);
        if (fileStats.length === 0) {
          const lines = patch.split("\n");
          bucket.push("patch");
          editStats.get(name)!.push({
            del: lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length,
            add: lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length,
          });
          break;
        }
        for (const fileStat of fileStats) {
          bucket.push(fileStat.name);
          editStats.get(name)!.push({ del: fileStat.del ?? 0, add: fileStat.add });
        }
        break;
      }
      case "Bash": {
        const summaries =
          typeof args.command === "string" ? extractBashSummaries(args.command) : [];
        bucket.push(...summaries);
        break;
      }
      case "WebFetch": {
        try {
          const host = typeof args.url === "string" ? new URL(args.url).hostname : null;
          if (host) bucket.push(host);
        } catch {
          /* ignore invalid URLs */
        }
        break;
      }
      case "WebSearch": {
        const q = typeof args.query === "string" ? args.query : null;
        if (q) bucket.push(q);
        break;
      }
    }
  }

  // Stable ordering: edits first, then execution, then reads, then web
  const TOOL_ORDER: Record<string, number> = {
    Edit: 0,
    Write: 1,
    apply_patch: 2,
    Bash: 3,
    Read: 4,
    WebFetch: 5,
    WebSearch: 6,
  };
  const sortedEntries = [...grouped.entries()]
    .filter(([, values]) => values.length > 0)
    .sort(([a], [b]) => (TOOL_ORDER[a] ?? 99) - (TOOL_ORDER[b] ?? 99));

  const parts: SummaryPart[] = [];
  for (const [name, values] of sortedEntries) {
    const unique = [...new Set(values)];
    switch (name) {
      case "Read": {
        const shown = unique.slice(0, 3).join(", ");
        const value = unique.length > 3 ? `${shown} +${unique.length - 3}` : shown;
        parts.push({ label: t("collapse.read"), value });
        break;
      }
      case "Edit": {
        const stats = editStats.get(name) ?? [];
        const merged = new Map<string, { del: number; add: number }>();
        for (let i = 0; i < values.length; i++) {
          const fname = values[i]!;
          const s = stats[i] ?? { del: 0, add: 0 };
          const existing = merged.get(fname);
          if (existing) {
            existing.del += s.del;
            existing.add += s.add;
          } else merged.set(fname, { del: s.del, add: s.add });
        }
        const fileStats = [...merged.entries()].map(([name, s]) => ({
          name,
          del: s.del,
          add: s.add,
        }));
        parts.push({ label: t("collapse.edited"), value: "", fileStats });
        break;
      }
      case "Write": {
        const stats = editStats.get(name) ?? [];
        const merged = new Map<string, { add: number }>();
        for (let i = 0; i < values.length; i++) {
          const fname = values[i]!;
          const s = stats[i] ?? { add: 0 };
          const existing = merged.get(fname);
          if (existing) {
            existing.add += s.add;
          } else merged.set(fname, { add: s.add });
        }
        const fileStats = [...merged.entries()].map(([name, s]) => ({ name, add: s.add }));
        parts.push({ label: t("collapse.wrote"), value: "", fileStats });
        break;
      }
      case "apply_patch": {
        const stats = editStats.get(name) ?? [];
        const merged = new Map<string, { del: number; add: number }>();
        for (let i = 0; i < values.length; i++) {
          const fname = values[i]!;
          const s = stats[i] ?? { del: 0, add: 0 };
          const existing = merged.get(fname);
          if (existing) {
            existing.del += s.del;
            existing.add += s.add;
          } else merged.set(fname, { del: s.del, add: s.add });
        }
        const fileStats = [...merged.entries()].map(([name, s]) => ({
          name,
          del: s.del,
          add: s.add,
        }));
        parts.push({ label: t("collapse.patched"), value: "", fileStats });
        break;
      }
      case "Bash":
        parts.push({
          label: t("collapse.ran"),
          value:
            unique.length > 5
              ? `${unique.slice(0, 5).join(", ")} +${unique.length - 5}`
              : unique.slice(0, 5).join(", "),
        });
        break;
      case "WebFetch":
        parts.push({ label: t("collapse.fetch"), value: unique[0]! });
        break;
      case "WebSearch": {
        const q = unique[0]!;
        parts.push({
          label: t("collapse.search"),
          value: q.length > 30 ? q.slice(0, 30) + "…" : q,
        });
        break;
      }
    }
  }

  return parts;
}

function summaryToText(summary: SummaryPart[]): string {
  return summary
    .map((part) => {
      if (part.fileStats) {
        const files = part.fileStats
          .map((fs) => {
            const stats = fs.del !== undefined ? `(-${fs.del} +${fs.add})` : `(+${fs.add})`;
            return `${fs.name} ${stats}`;
          })
          .join(", ");
        return `${part.label} ${files}`;
      }
      return `${part.label} ${part.value}`;
    })
    .join(" \u00b7 ");
}

function SummaryDisplay({ summary }: { summary: SummaryPart[] }): JSX.Element {
  return (
    <>
      {summary.map((part, partIdx) => (
        <span key={partIdx}>
          {partIdx > 0 ? <span className="mx-1.5 text-neutral-400">{"\u00b7"}</span> : null}
          {part.fileStats ? (
            <>
              <span className="font-normal text-neutral-500">{part.label}</span>{" "}
              {part.fileStats.map((fs, fsIdx) => (
                <span key={fsIdx}>
                  {fsIdx > 0 ? ", " : null}
                  {fs.name}
                  {" ( "}
                  {fs.del !== undefined && fs.del > 0 ? (
                    <span className="text-red-600">-{fs.del}</span>
                  ) : null}
                  {fs.del !== undefined && fs.del > 0 && fs.add > 0 ? " " : null}
                  {fs.add > 0 ? <span className="text-emerald-600">+{fs.add}</span> : null}
                  {" )"}
                </span>
              ))}
            </>
          ) : (
            <>
              <span className="font-normal text-neutral-500">{part.label}</span>{" "}
              <span style={{ fontSize: "0.9em" }}>{part.value}</span>
            </>
          )}
        </span>
      ))}
    </>
  );
}

export function CollapseGroupBlock({
  items,
  collapsed,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
}: CollapseGroupBlockProps): JSX.Element {
  const t = useT();
  const toolCount = items.filter((item) => item.type === "tool_block").length;
  const stepLabel = toolCount > 0 ? t("collapse.toolsUsed")(toolCount) : t("collapse.thoughts");
  const summary = useMemo(() => summarizeCollapseItems(items, t), [items, t]);
  const summaryText = useMemo(() => summaryToText(summary), [summary]);
  const summarySpanRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    const el = summarySpanRef.current;
    if (!el) return;
    const check = () => setIsTruncated(el.scrollWidth > el.clientWidth);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [summaryText]);

  // Group consecutive developer_message items so they render as one merged row
  type RenderBlock =
    | { kind: "dev"; items: DeveloperMessageItem[] }
    | { kind: "other"; item: MessageItemType };

  const renderBlocks = useMemo((): RenderBlock[] => {
    const result: RenderBlock[] = [];
    for (const item of items) {
      if (item.type === "developer_message") {
        const last = result[result.length - 1];
        if (last?.kind === "dev") {
          last.items.push(item);
        } else {
          result.push({ kind: "dev", items: [item] });
        }
      } else {
        result.push({ kind: "other", item });
      }
    }
    return result;
  }, [items]);

  return (
    <div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onToggle}
            className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start py-1 text-left text-base text-neutral-500 transition-colors hover:text-neutral-600`}
          >
            <CollapseRailMarker open={!collapsed} />
            <span className="flex min-w-0 items-center">
              {summary.length === 0 ? (
                <span className="min-w-0 truncate">{stepLabel}</span>
              ) : (
                <span ref={summarySpanRef} className="min-w-0 truncate text-neutral-500">
                  <SummaryDisplay summary={summary} />
                </span>
              )}
            </span>
          </button>
        </TooltipTrigger>
        {isTruncated ? (
          <TooltipContent side="bottom" align="start">
            {summaryText}
          </TooltipContent>
        ) : null}
      </Tooltip>
      {/* grid-template-rows trick: 0fr→1fr gives smooth height transition without JS height measurement */}
      <CollapseRailPanel open={!collapsed}>
        <div className={`mt-1.5 grid min-w-0 items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME}`}>
          <CollapseRailConnector lineClassName="-mt-1.5" />
          <div className="min-w-0 space-y-3 pb-1">
            {renderBlocks.map((block, idx) => {
              if (block.kind === "dev") {
                return <DeveloperMessage key={`dev-${idx}`} items={block.items} />;
              }
              return (
                <MessageRow
                  key={block.item.id}
                  item={block.item}
                  workDir={workDir}
                  isActive={block.item.id === activeItemId}
                  copied={copiedItemId === block.item.id}
                  onCopy={onCopy}
                  itemRef={(el: HTMLDivElement | null) => setItemRef(block.item.id, el)}
                />
              );
            })}
          </div>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
