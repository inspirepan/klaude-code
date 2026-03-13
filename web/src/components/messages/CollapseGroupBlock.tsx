import { useMemo } from "react";

import type { MessageItem as MessageItemType, DeveloperMessageItem } from "../../types/message";
import { MessageRow } from "./MessageRow";
import { DeveloperMessage } from "./DeveloperMessage";

interface CollapseGroupBlockProps {
  items: MessageItemType[];
  collapsed: boolean;
  showRunningSpinner: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

// Commands that take a meaningful subcommand as their second token
const SUBCOMMAND_COMMANDS = new Set([
  "git",
  "jj",
  "hg",
  "svn",
  "docker",
  "docker-compose",
  "podman",
  "kubectl",
  "helm",
  "npm",
  "yarn",
  "pnpm",
  "cargo",
  "uv",
  "pip",
  "poetry",
  "brew",
  "apt",
  "apt-get",
  "dnf",
  "yum",
  "pacman",
  "aws",
  "gcloud",
  "az",
  "go",
  "rustup",
  "python",
  "ruby",
  "gh",
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

function extractCommandFromStatement(stmt: string): string | null {
  const tokens = stmt.trim().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return null;
  const cmd = tokens[0]!;
  if (IGNORED_COMMANDS.has(cmd)) return null;
  if (SUBCOMMAND_COMMANDS.has(cmd)) {
    for (let i = 1; i < tokens.length; i++) {
      if (!tokens[i]!.startsWith("-")) {
        return `${cmd} ${tokens[i]}`;
      }
    }
  }
  return cmd;
}

function extractBashSummary(command: string): string | null {
  // Split by statement separators; pipe | is not a separator (it chains, not sequences)
  const statements = command.split(/&&|\|\||[;\n]/);
  for (const stmt of statements) {
    const result = extractCommandFromStatement(stmt);
    if (result !== null) return result;
  }
  return null;
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
      if (unifiedCurrent?.name !== name) {
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

function summarizeCollapseItems(items: MessageItemType[]): SummaryPart[] {
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
        const del = typeof args.old_string === "string" ? args.old_string.split("\n").length : 0;
        const add = typeof args.new_string === "string" ? args.new_string.split("\n").length : 0;
        bucket.push(p);
        if (!editStats.has(name)) editStats.set(name, []);
        editStats.get(name)!.push({ del, add });
        break;
      }
      case "Write": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (!p) break;
        const add = typeof args.content === "string" ? args.content.split("\n").length : 0;
        bucket.push(p);
        if (!editStats.has(name)) editStats.set(name, []);
        editStats.get(name)!.push({ del: 0, add });
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
        const s = typeof args.command === "string" ? extractBashSummary(args.command) : null;
        if (s) bucket.push(s);
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

  const parts: SummaryPart[] = [];
  for (const [name, values] of grouped) {
    if (values.length === 0) continue;
    const unique = [...new Set(values)];
    switch (name) {
      case "Read": {
        const shown = unique.slice(0, 3).join(", ");
        const value = unique.length > 3 ? `${shown} +${unique.length - 3}` : shown;
        parts.push({ label: "Read", value });
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
        parts.push({ label: "Edited", value: "", fileStats });
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
        parts.push({ label: "Wrote", value: "", fileStats });
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
        parts.push({ label: "Patched", value: "", fileStats });
        break;
      }
      case "Bash":
        parts.push({ label: "Ran", value: unique.slice(0, 2).join(", ") });
        break;
      case "WebFetch":
        parts.push({ label: "Fetch", value: unique[0]! });
        break;
      case "WebSearch": {
        const q = unique[0]!;
        parts.push({ label: "Search", value: q.length > 30 ? q.slice(0, 30) + "…" : q });
        break;
      }
    }
  }

  return parts;
}

export function CollapseGroupBlock({
  items,
  collapsed,
  showRunningSpinner,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
}: CollapseGroupBlockProps): JSX.Element {
  const toolCount = items.filter((item) => item.type === "tool_block").length;
  const stepLabel =
    toolCount > 0 ? `${toolCount} tool${toolCount === 1 ? "" : "s"} used` : "Thoughts";
  const summary = useMemo(() => summarizeCollapseItems(items), [items]);

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
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full min-w-0 grid-cols-[28px_1fr] items-start py-0.5 text-left text-sm text-neutral-400 transition-colors hover:text-neutral-600"
      >
        <span className="flex justify-center pt-0.5 font-mono text-xs text-neutral-400">
          {collapsed ? "[+]" : "[-]"}
        </span>
        <span className="flex min-w-0 items-center gap-1.5 pl-1">
          <span className="shrink-0 font-mono">{stepLabel}</span>
          {summary.length > 0 ? <span className="shrink-0 text-neutral-300">,</span> : null}
          {summary.length > 0 ? (
            <span className="flex min-w-0 items-center truncate pl-1">
              {summary.map((part, i) => (
                <span
                  key={i}
                  className={`flex shrink-0 items-center gap-2 ${i < summary.length - 1 ? "mr-2" : ""}`}
                >
                  <span className="font-mono text-neutral-500">{part.label}</span>
                  {part.fileStats ? (
                    part.fileStats.map((fs, j) => (
                      <span key={j} className="flex shrink-0 items-center gap-1">
                        {j > 0 ? <span className="text-neutral-300">,</span> : null}
                        <span className="font-mono text-neutral-400">{fs.name}</span>
                        <span className="font-mono text-neutral-300">
                          {"("}
                          {fs.del !== undefined ? (
                            <span className="text-rose-500">-{fs.del}</span>
                          ) : null}
                          {fs.del !== undefined ? <span> </span> : null}
                          <span className="text-emerald-600">+{fs.add}</span>
                          {")"}
                        </span>
                      </span>
                    ))
                  ) : (
                    <>
                      <span className="font-mono text-neutral-400">{part.value}</span>
                      {part.del !== undefined || part.add !== undefined ? (
                        <span className="font-mono text-neutral-300">
                          {"("}
                          {part.del !== undefined ? (
                            <span className="text-rose-500">-{part.del}</span>
                          ) : null}
                          {part.del !== undefined && part.add !== undefined ? <span> </span> : null}
                          {part.add !== undefined ? (
                            <span className="text-emerald-600">+{part.add}</span>
                          ) : null}
                          {")"}
                        </span>
                      ) : null}
                    </>
                  )}
                  {i < summary.length - 1 ? <span className="text-neutral-300">,</span> : null}
                </span>
              ))}
            </span>
          ) : null}
        </span>
      </button>
      {/* grid-template-rows trick: 0fr→1fr gives smooth height transition without JS height measurement */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-200 ease-in-out"
        style={{
          gridTemplateRows: collapsed ? "0fr" : "1fr",
          opacity: collapsed ? 0 : 1,
        }}
      >
        <div className="overflow-hidden">
          <div className="mt-2 grid grid-cols-[28px_1fr]">
            <div className="flex justify-center">
              <div className="-mt-2 w-px self-stretch bg-neutral-200" />
            </div>
            <div className="min-w-0 space-y-5 pb-1">
              {renderBlocks.map((block, idx) => {
                if (block.kind === "dev") {
                  return <DeveloperMessage key={`dev-${idx}`} items={block.items} />;
                }
                return (
                  <MessageRow
                    key={block.item.id}
                    item={block.item}
                    variant="main"
                    workDir={workDir}
                    isActive={block.item.id === activeItemId}
                    copied={copiedItemId === block.item.id}
                    onCopy={onCopy}
                    itemRef={(el: HTMLDivElement | null) => setItemRef(block.item.id, el)}
                  />
                );
              })}
            </div>
            {showRunningSpinner ? (
              <>
                <div className="-mt-0.5 flex justify-center">
                  <div className="flex flex-col items-center">
                    <div className="h-2 w-px bg-neutral-200" />
                    <span className="mt-0.5 h-3 w-3 shrink-0 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
                  </div>
                </div>
                <div aria-hidden="true" className="h-5" />
              </>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
